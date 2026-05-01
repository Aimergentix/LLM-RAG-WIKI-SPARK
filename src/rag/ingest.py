"""M8 RAG ingest orchestrator.

Per START-PROMPT §5 M8 contract; MASTER §6 (RAG P2 Ingest), §7 (manifest
schema, stable chunk IDs), §8 (security: untrusted markdown, symlink
rejection), §9 (error taxonomy).

Pure stdlib at module level. Embedder/store backends are loaded
lazily — production backends import ``sentence-transformers`` and
``chromadb`` only inside their own ``__init__`` methods.

CLI: ``python -m rag.ingest [--config PATH] [--reset]``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rag.chunker import Chunk, chunk_markdown
from rag.config import Config, ConfigError, config_hash, load_config
from rag.manifest import (
    ERR_INDEX_MISSING,
    FileEntry,
    Manifest,
    ManifestError,
    load_manifest,
    save_manifest,
)
from rag.security import is_injection_flagged
from rag.store import VectorStore

ERR_SECURITY = "[ERR_SECURITY]"
ERR_RUNTIME = "[ERR_RUNTIME]"

LOG = logging.getLogger("rag.ingest")

_PRIVACY_MARKERS = ("secret", "private")


@dataclass(frozen=True)
class IngestStats:
    files_scanned: int
    files_indexed: int
    files_skipped: int
    chunks_upserted: int
    chunks_deleted: int
    embedding_seconds: float


# ---------------------------------------------------------------- helpers


def _isoformat_utc(today: str | None = None) -> str:
    if today is not None:
        return today
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_secret_frontmatter(text: str) -> bool:
    """Return True iff a top-level YAML frontmatter declares ``privacy: secret``."""
    if not text.startswith("---"):
        return False
    lines = text.split("\n", 200)
    if len(lines) < 2:
        return False
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return False
    for raw in lines[1:end]:
        s = raw.strip()
        if not s.lower().startswith("privacy"):
            continue
        _, _, val = s.partition(":")
        v = val.strip().strip('"').strip("'").lower()
        if v in _PRIVACY_MARKERS:
            return True
    return False


def _contains_injection(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _INJECTION_MARKERS)


def _scan_markdown(wiki_root: Path) -> list[Path]:
    """Return sorted ``*.md`` files inside ``wiki_root.resolve()``.

    Files reachable only via symlinks that escape the resolved root
    are silently dropped (with a logged warning).
    """
    root = wiki_root.resolve()
    out: list[Path] = []
    for p in sorted(wiki_root.rglob("*.md")):
        try:
            resolved = p.resolve()
        except OSError as exc:
            LOG.warning("rag.ingest skip unreadable path %s: %s", p, exc)
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            LOG.warning(
                "rag.ingest skip path outside wiki_root (symlink escape?): %s", p
            )
            continue
        if not resolved.is_file():
            continue
        out.append(resolved)
    return out


def _build_embedder(cfg: Config):
    if os.environ.get("LLM_RAG_WIKI_TEST_STUB_EMBEDDER") == "1":
        from rag.embedder import DeterministicHashEmbedder  # noqa: PLC0415

        return DeterministicHashEmbedder(dim=16)
    from rag.embedder import SentenceTransformersEmbedder  # noqa: PLC0415

    return SentenceTransformersEmbedder(
        cfg.embedding.model_id,
        normalize=cfg.embedding.normalize_embeddings,
    )


def _build_store(cfg: Config, *, collection_name: str) -> VectorStore:
    from rag.store import ChromaVectorStore  # noqa: PLC0415

    return ChromaVectorStore(
        cfg.paths.index_dir,
        collection_name,
        distance_metric=cfg.retrieval.distance_metric,
    )


def _shadow_collection_name(base: str) -> str:
    return base + "__shadow"


def _build_metadatas(chunks: list[Chunk]) -> list[dict]:
    return [
        {
            "rel_path": c.rel_path,
            "heading_path": c.heading_path,
            "chunk_index": c.chunk_index,
            "chunk_hash": c.chunk_hash,
        }
        for c in chunks
    ]


# ---------------------------------------------------------------- core API


def ingest_wiki(
    cfg: Config,
    *,
    embedder=None,
    store: VectorStore | None = None,
    today: str | None = None,
    reset: bool = False,
) -> IngestStats:
    """Run the M8 ingest pipeline against ``cfg.paths.wiki_root``."""
    wiki_root = cfg.paths.wiki_root
    if not wiki_root.is_dir():
        raise ManifestError(
            f"{ERR_INDEX_MISSING} wiki_root not found or not a directory: {wiki_root}"
        )
    if Path(wiki_root).is_symlink():
        raise ConfigError(
            f"{ERR_SECURITY} paths.wiki_root must not be a symlink: {wiki_root}"
        )

    cfg_hash = config_hash(cfg)
    collection_name = cfg.domain.name
    manifest_path = cfg.paths.manifest_path

    try:
        prior = load_manifest(manifest_path)
    except ManifestError as exc:
        msg = str(exc)
        if msg.startswith(ERR_INDEX_MISSING):
            prior = Manifest(
                schema_version=1,
                config_hash=cfg_hash,
                created_at=_isoformat_utc(today),
                updated_at=_isoformat_utc(today),
                files={},
            )
        else:
            raise

    own_store = store is None
    if embedder is None:
        embedder = _build_embedder(cfg)

    use_atomic = bool(reset and cfg.indexing.atomic_reindex)

    primary_store: VectorStore
    write_store: VectorStore
    if own_store:
        if use_atomic:
            primary_store = _build_store(cfg, collection_name=collection_name)
            write_store = _build_store(
                cfg, collection_name=_shadow_collection_name(collection_name)
            )
        else:
            primary_store = _build_store(cfg, collection_name=collection_name)
            write_store = primary_store
            if reset:
                write_store.reset()
    else:
        primary_store = store  # type: ignore[assignment]
        if use_atomic:
            from rag.store import InMemoryVectorStore  # noqa: PLC0415

            write_store = InMemoryVectorStore()
        else:
            write_store = primary_store
            if reset:
                write_store.reset()

    files = _scan_markdown(wiki_root)
    stats_scanned = len(files)
    stats_indexed = 0
    stats_skipped = 0
    stats_chunks_up = 0
    stats_chunks_del = 0
    embed_seconds = 0.0

    new_files: dict[str, FileEntry] = {}
    seen_rel: set[str] = set()
    config_unchanged = prior.config_hash == cfg_hash

    try:
        for fpath in files:
            rel_path = str(fpath.relative_to(wiki_root.resolve()).as_posix())
            seen_rel.add(rel_path)
            try:
                file_bytes = fpath.read_bytes()
            except OSError as exc:
                LOG.warning("rag.ingest skip unreadable %s: %s", rel_path, exc)
                continue
            text = file_bytes.decode("utf-8", errors="replace")

            if cfg.privacy.block_secret_chunks and _is_secret_frontmatter(text):
                LOG.info("rag.ingest skip secret-marked %s", rel_path)
                stats_skipped += 1
                old_entry = prior.files.get(rel_path)
                if old_entry is not None and not use_atomic:
                    write_store.delete(list(old_entry.chunk_ids))
                    stats_chunks_del += len(old_entry.chunk_ids)
                continue

            source_hash = _sha256_bytes(file_bytes)
            prior_entry = prior.files.get(rel_path)
            if (
                not reset
                and prior_entry is not None
                and config_unchanged
                and prior_entry.source_hash == source_hash
            ):
                stats_skipped += 1
                new_files[rel_path] = prior_entry
                continue

            chunks = chunk_markdown(
                text,
                rel_path=rel_path,
                collection_name=collection_name,
                min_chars=cfg.chunking.min_chars,
                max_chars=cfg.chunking.max_chars,
            )

            if prior_entry is not None and not use_atomic:
                write_store.delete(list(prior_entry.chunk_ids))
                stats_chunks_del += len(prior_entry.chunk_ids)

            if not chunks:
                new_files[rel_path] = FileEntry(source_hash=source_hash, chunk_ids=[])
                stats_indexed += 1
                continue

            ids = [c.chunk_id for c in chunks]
            metadatas = _build_metadatas(chunks)
            documents = [c.text for c in chunks]

            t0 = time.monotonic()
            embeddings = embedder.embed(documents)
            embed_seconds += time.monotonic() - t0

            write_store.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            )
            for c in chunks:
                if is_injection_flagged(c.text):
                    LOG.info(
                        "rag.ingest indexed potentially injection-flagged chunk:"
                        " rel_path=%s heading=%s chunk_index=%d (text suppressed)",
                        c.rel_path,
                        c.heading_path,
                        c.chunk_index,
                    )
            stats_chunks_up += len(chunks)
            stats_indexed += 1
            new_files[rel_path] = FileEntry(source_hash=source_hash, chunk_ids=ids)

        if not use_atomic:
            for rel_path, prior_entry in prior.files.items():
                if rel_path in seen_rel:
                    continue
                write_store.delete(list(prior_entry.chunk_ids))
                stats_chunks_del += len(prior_entry.chunk_ids)
    except BaseException:
        if use_atomic and own_store:
            try:
                from rag.store import ChromaVectorStore  # noqa: PLC0415

                if isinstance(write_store, ChromaVectorStore):
                    write_store._client.delete_collection(  # noqa: SLF001
                        _shadow_collection_name(collection_name)
                    )
            except Exception:  # pragma: no cover — best-effort
                LOG.warning("rag.ingest failed to drop shadow collection cleanly")
        raise

    if use_atomic:
        if own_store:
            from rag.store import ChromaVectorStore  # noqa: PLC0415

            if isinstance(write_store, ChromaVectorStore) and isinstance(
                primary_store, ChromaVectorStore
            ):
                try:
                    primary_store._client.delete_collection(collection_name)  # noqa: SLF001
                except Exception:  # noqa: BLE001
                    pass
                try:
                    write_store._collection.modify(name=collection_name)  # noqa: SLF001
                except Exception as exc:  # noqa: BLE001
                    LOG.warning(
                        "rag.ingest atomic reindex rename failed; primary not swapped: %s",
                        exc,
                    )
        else:
            primary_store.reset()
            from rag.store import InMemoryVectorStore  # noqa: PLC0415

            if isinstance(write_store, InMemoryVectorStore):
                ids_all = write_store.ids()
                if ids_all:
                    embs: list[list[float]] = []
                    metas: list[dict] = []
                    docs: list[str] = []
                    for _id in ids_all:
                        rec = write_store.get(_id)
                        assert rec is not None
                        embs.append(rec["embedding"])
                        metas.append(rec["metadata"])
                        docs.append(rec["document"])
                    primary_store.upsert(ids_all, embs, metas, docs)

    new_manifest = Manifest(
        schema_version=1,
        config_hash=cfg_hash,
        created_at=prior.created_at,
        updated_at=_isoformat_utc(today),
        files=new_files,
    )
    save_manifest(manifest_path, new_manifest)

    return IngestStats(
        files_scanned=stats_scanned,
        files_indexed=stats_indexed,
        files_skipped=stats_skipped,
        chunks_upserted=stats_chunks_up,
        chunks_deleted=stats_chunks_del,
        embedding_seconds=embed_seconds,
    )


# ---------------------------------------------------------------- CLI


def _make_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rag.ingest", description=__doc__)
    p.add_argument("--config", default=None, help="path to config.yaml")
    p.add_argument("--reset", action="store_true", help="rebuild from scratch")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _make_arg_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        stats = ingest_wiki(cfg, reset=args.reset)
    except (ConfigError, ManifestError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"{ERR_RUNTIME} {exc}", file=sys.stderr)
        return 3
    print(
        "INGEST COMPLETE"
        f" scanned={stats.files_scanned}"
        f" indexed={stats.files_indexed}"
        f" skipped={stats.files_skipped}"
        f" chunks_upserted={stats.chunks_upserted}"
        f" chunks_deleted={stats.chunks_deleted}"
        f" embedding_seconds={stats.embedding_seconds:.3f}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

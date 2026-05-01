"""M7 RAG configuration loader, validator, and typed accessor.

Per START-PROMPT §5 M7 contract; MASTER §7 (RAG Schemas), §8 (security),
§9 ([ERR_CONFIG]).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

ERR_CONFIG = "[ERR_CONFIG]"


class ConfigError(Exception):
    """Raised on any configuration validation failure.

    Message always begins with ``[ERR_CONFIG]``.
    """


# ---------------------------------------------------------------- dataclasses

@dataclass(frozen=True)
class ProjectConfig:
    name: str
    role: str
    version: str


@dataclass(frozen=True)
class RuntimeConfig:
    python_min: str
    log_format: str


@dataclass(frozen=True)
class DomainConfig:
    name: str


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    model_id: str
    normalize_embeddings: bool


@dataclass(frozen=True)
class PathsConfig:
    wiki_root: Path
    index_dir: Path
    manifest_path: Path


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str
    min_chars: int
    max_chars: int


@dataclass(frozen=True)
class RerankingConfig:
    enabled: bool
    model_id: str
    top_n: int


@dataclass(frozen=True)
class SnapshotConfig:
    enabled: bool
    backup_dir: Path


@dataclass(frozen=True)
class IndexingConfig:
    atomic_reindex: bool


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int
    distance_metric: str
    min_score: float
    ood_threshold: float
    mmr_enabled: bool
    mmr_lambda: float


@dataclass(frozen=True)
class PrivacyConfig:
    block_secret_chunks: bool


@dataclass(frozen=True)
class Config:
    schema_version: int
    project: ProjectConfig
    runtime: RuntimeConfig
    domain: DomainConfig
    embedding: EmbeddingConfig
    paths: PathsConfig
    reranking: RerankingConfig
    snapshot: SnapshotConfig
    chunking: ChunkingConfig
    indexing: IndexingConfig
    retrieval: RetrievalConfig
    privacy: PrivacyConfig


# ---------------------------------------------------------------- helpers

def _leaf(raw: dict, field_path: str, type_: type) -> object:  # noqa: ANN401
    """Retrieve and type-check a dotted-path field; raise ConfigError on failure."""
    parts = field_path.split(".")
    obj: object = raw
    for i, key in enumerate(parts):
        if not isinstance(obj, dict):
            parent = ".".join(parts[:i]) or "(root)"
            raise ConfigError(
                f"{ERR_CONFIG} field '{parent}' must be a mapping"
            )
        if key not in obj:
            raise ConfigError(
                f"{ERR_CONFIG} missing required field: {'.'.join(parts[:i + 1])}"
            )
        obj = obj[key]  # type: ignore[index]

    # type check
    if type_ is bool:
        if not isinstance(obj, bool):
            raise ConfigError(
                f"{ERR_CONFIG} field '{field_path}' must be bool,"
                f" got {type(obj).__name__}"
            )
        return obj
    if type_ is int:
        if isinstance(obj, bool) or not isinstance(obj, int):
            raise ConfigError(
                f"{ERR_CONFIG} field '{field_path}' must be int,"
                f" got {type(obj).__name__}"
            )
        return obj
    if type_ is float:
        if isinstance(obj, bool) or not isinstance(obj, (int, float)):
            raise ConfigError(
                f"{ERR_CONFIG} field '{field_path}' must be float,"
                f" got {type(obj).__name__}"
            )
        return float(obj)
    if type_ is str:
        if not isinstance(obj, str):
            raise ConfigError(
                f"{ERR_CONFIG} field '{field_path}' must be str,"
                f" got {type(obj).__name__}"
            )
        return obj
    return obj


def _section(raw: dict, key: str) -> dict:
    """Return a required dict section; raise ConfigError if missing or wrong type."""
    if key not in raw:
        raise ConfigError(f"{ERR_CONFIG} missing required section: {key}")
    val = raw[key]
    if not isinstance(val, dict):
        raise ConfigError(
            f"{ERR_CONFIG} section '{key}' must be a mapping,"
            f" got {type(val).__name__}"
        )
    return val  # type: ignore[return-value]


def _resolve_path(raw_val: object, field_path: str, base_dir: Path) -> Path:
    """Resolve a path field relative to base_dir; raise ConfigError on bad type."""
    if not isinstance(raw_val, str):
        raise ConfigError(
            f"{ERR_CONFIG} field '{field_path}' must be str,"
            f" got {type(raw_val).__name__}"
        )
    p = Path(raw_val)
    if not p.is_absolute():
        p = base_dir / p
    return p.resolve()


def _check_wiki_root(resolved: Path) -> None:
    """Reject wiki_root that descends through an entry/ or raw/ component."""
    if "entry" in resolved.parts or "raw" in resolved.parts:
        raise ConfigError(
            f"{ERR_CONFIG} paths.wiki_root must not be under entry/ or raw/:"
            f" {resolved}"
        )


# ---------------------------------------------------------------- parser

def _parse(raw: dict, config_dir: Path) -> Config:
    """Build and validate a Config from the parsed YAML dict."""
    # schema_version
    sv = raw.get("schema_version", _MISSING := object())
    if sv is _MISSING:
        raise ConfigError(f"{ERR_CONFIG} missing required field: schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int) or sv != 1:
        raise ConfigError(
            f"{ERR_CONFIG} schema_version must be integer 1, got {sv!r}"
        )

    # project
    proj = _section(raw, "project")
    project = ProjectConfig(
        name=_leaf(proj, "name", str),  # type: ignore[arg-type]
        role=_leaf(proj, "role", str),  # type: ignore[arg-type]
        version=_leaf(proj, "version", str),  # type: ignore[arg-type]
    )

    # runtime
    rt = _section(raw, "runtime")
    runtime = RuntimeConfig(
        python_min=_leaf(rt, "python_min", str),  # type: ignore[arg-type]
        log_format=_leaf(rt, "log_format", str),  # type: ignore[arg-type]
    )

    # domain
    dom = _section(raw, "domain")
    domain = DomainConfig(
        name=_leaf(dom, "name", str),  # type: ignore[arg-type]
    )

    # embedding
    emb = _section(raw, "embedding")
    embedding = EmbeddingConfig(
        provider=_leaf(emb, "provider", str),  # type: ignore[arg-type]
        model_id=_leaf(emb, "model_id", str),  # type: ignore[arg-type]
        normalize_embeddings=_leaf(emb, "normalize_embeddings", bool),  # type: ignore[arg-type]
    )

    # paths
    paths_raw = _section(raw, "paths")
    wiki_root = _resolve_path(
        paths_raw.get("wiki_root"), "paths.wiki_root", config_dir
    )
    _check_wiki_root(wiki_root)
    paths = PathsConfig(
        wiki_root=wiki_root,
        index_dir=_resolve_path(
            paths_raw.get("index_dir"), "paths.index_dir", config_dir
        ),
        manifest_path=_resolve_path(
            paths_raw.get("manifest_path"), "paths.manifest_path", config_dir
        ),
    )

    # reranking
    rr = _section(raw, "reranking")
    reranking = RerankingConfig(
        enabled=_leaf(rr, "enabled", bool),  # type: ignore[arg-type]
        model_id=_leaf(rr, "model_id", str),  # type: ignore[arg-type]
        top_n=_leaf(rr, "top_n", int),  # type: ignore[arg-type]
    )

    # chunking
    chk = _section(raw, "chunking")
    min_chars: int = _leaf(chk, "min_chars", int)  # type: ignore[assignment]
    max_chars: int = _leaf(chk, "max_chars", int)  # type: ignore[assignment]
    if min_chars < 1:
        raise ConfigError(
            f"{ERR_CONFIG} chunking.min_chars must be >= 1, got {min_chars}"
        )
    if max_chars <= min_chars:
        raise ConfigError(
            f"{ERR_CONFIG} chunking.max_chars must be > min_chars"
            f" ({min_chars}), got {max_chars}"
        )
    chunking = ChunkingConfig(
        strategy=_leaf(chk, "strategy", str),  # type: ignore[arg-type]
        min_chars=min_chars,
        max_chars=max_chars,
    )

    # indexing
    idx = _section(raw, "indexing")
    indexing = IndexingConfig(
        atomic_reindex=_leaf(idx, "atomic_reindex", bool),  # type: ignore[arg-type]
    )

    # retrieval
    ret = _section(raw, "retrieval")
    top_k: int = _leaf(ret, "top_k", int)  # type: ignore[assignment]
    min_score: float = _leaf(ret, "min_score", float)  # type: ignore[assignment]
    ood_threshold: float = _leaf(ret, "ood_threshold", float)  # type: ignore[assignment]
    if not (0.0 <= ood_threshold <= 1.0):
        raise ConfigError(
            f"{ERR_CONFIG} retrieval.ood_threshold must be in [0.0, 1.0],"
            f" got {ood_threshold}"
        )
    if not (0.0 <= min_score <= 1.0):
        raise ConfigError(
            f"{ERR_CONFIG} retrieval.min_score must be in [0.0, 1.0],"
            f" got {min_score}"
        )
    if ood_threshold > min_score:
        raise ConfigError(
            f"{ERR_CONFIG} retrieval.ood_threshold ({ood_threshold})"
            f" must be <= min_score ({min_score})"
        )
    retrieval = RetrievalConfig(
        top_k=top_k,
        distance_metric=_leaf(ret, "distance_metric", str),  # type: ignore[arg-type]
        min_score=min_score,
        ood_threshold=ood_threshold,
        mmr_enabled=_leaf(ret, "mmr_enabled", bool),  # type: ignore[arg-type]
        mmr_lambda=_leaf(ret, "mmr_lambda", float),  # type: ignore[arg-type]
    )

    # privacy
    priv = _section(raw, "privacy")
    privacy = PrivacyConfig(
        block_secret_chunks=_leaf(priv, "block_secret_chunks", bool),  # type: ignore[arg-type]
    )

    return Config(
        schema_version=sv,
        project=project,
        runtime=runtime,
        domain=domain,
        embedding=embedding,
        paths=paths,
        reranking=reranking,
        snapshot=snapshot,
        chunking=chunking,
        indexing=indexing,
        retrieval=retrieval,
        privacy=privacy,
    )


# ---------------------------------------------------------------- public API

def load_config(path: str | Path | None = None) -> Config:
    """Load, validate, and return a frozen :class:`Config`.

    Resolution order:

    1. Explicit *path* argument.
    2. ``LLM_RAG_WIKI_CONFIG`` environment variable.
    3. ``config.yaml`` three directories above this file (the repo root).

    Raises :class:`ConfigError` (carrying ``[ERR_CONFIG]``) on any failure.
    CLI callers should map ``ConfigError`` to exit code 2.
    """
    if path is not None:
        config_path = Path(path)
    elif "LLM_RAG_WIKI_CONFIG" in os.environ:
        config_path = Path(os.environ["LLM_RAG_WIKI_CONFIG"])
    else:
        config_path = Path(__file__).parent.parent.parent / "config.yaml"

    config_path = Path(config_path).resolve()
    if not config_path.is_file():
        raise ConfigError(
            f"{ERR_CONFIG} config file not found: {config_path}"
        )

    try:
        import yaml  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError as exc:
        raise ConfigError(
            f"{ERR_CONFIG} pyyaml is required; install with: pip install pyyaml"
        ) from exc

    try:
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as exc:
        raise ConfigError(
            f"{ERR_CONFIG} failed to parse {config_path}: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigError(
            f"{ERR_CONFIG} config must be a YAML mapping,"
            f" got {type(raw).__name__}"
        )

    return _parse(raw, config_path.parent)


def config_hash(cfg: Config) -> str:
    """Return a stable SHA-256 hex digest of *cfg*.

    The hash is computed over a canonical, key-sorted JSON serialization so
    it is invariant to key order or whitespace differences in the source YAML.
    """
    raw = asdict(cfg)

    def _normalize(obj: object) -> object:
        if isinstance(obj, dict):
            return {k: _normalize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_normalize(i) for i in obj]
        if isinstance(obj, Path):
            return str(obj)
        return obj

    normalized = _normalize(raw)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()

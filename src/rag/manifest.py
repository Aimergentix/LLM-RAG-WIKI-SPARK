"""M8 RAG manifest — atomic JSON read/write of the per-file ingest manifest.

Per START-PROMPT §5 M8 contract; MASTER §7 (RAG manifest schema), §9
(``[ERR_INDEX_MISSING]`` / ``[ERR_SCHEMA]``).

Pure stdlib. No third-party imports at module level.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

ERR_INDEX_MISSING = "[ERR_INDEX_MISSING]"
ERR_SCHEMA = "[ERR_SCHEMA]"


class ManifestError(Exception):
    """Raised on manifest read failures.

    Message always begins with one of the M8 error codes
    (``[ERR_INDEX_MISSING]`` or ``[ERR_SCHEMA]``).
    """


# ---------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class FileEntry:
    source_hash: str
    chunk_ids: list[str]


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    config_hash: str
    created_at: str
    updated_at: str
    files: dict[str, FileEntry] = field(default_factory=dict)


# ---------------------------------------------------------------- I/O


def load_manifest(path: Path) -> Manifest:
    """Load and validate a manifest JSON file.

    Raises :class:`ManifestError` ``[ERR_INDEX_MISSING]`` if the file
    does not exist, ``[ERR_SCHEMA]`` if it cannot be parsed or is
    structurally invalid.
    """
    p = Path(path)
    if not p.is_file():
        raise ManifestError(f"{ERR_INDEX_MISSING} manifest not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{ERR_SCHEMA} malformed manifest JSON at {p}: {exc}") from exc
    except OSError as exc:
        raise ManifestError(f"{ERR_SCHEMA} unreadable manifest at {p}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError(f"{ERR_SCHEMA} manifest must be a JSON object, got {type(raw).__name__}")

    for key in ("schema_version", "config_hash", "created_at", "updated_at", "files"):
        if key not in raw:
            raise ManifestError(f"{ERR_SCHEMA} manifest missing required field: {key}")

    sv = raw["schema_version"]
    if isinstance(sv, bool) or not isinstance(sv, int):
        raise ManifestError(f"{ERR_SCHEMA} schema_version must be int, got {type(sv).__name__}")
    for str_key in ("config_hash", "created_at", "updated_at"):
        if not isinstance(raw[str_key], str):
            raise ManifestError(
                f"{ERR_SCHEMA} field '{str_key}' must be str, got {type(raw[str_key]).__name__}"
            )
    files_raw = raw["files"]
    if not isinstance(files_raw, dict):
        raise ManifestError(f"{ERR_SCHEMA} files must be a mapping, got {type(files_raw).__name__}")

    files: dict[str, FileEntry] = {}
    for rel_path, entry in files_raw.items():
        if not isinstance(rel_path, str):
            raise ManifestError(f"{ERR_SCHEMA} files key must be str, got {type(rel_path).__name__}")
        if not isinstance(entry, dict):
            raise ManifestError(
                f"{ERR_SCHEMA} files['{rel_path}'] must be a mapping,"
                f" got {type(entry).__name__}"
            )
        if "source_hash" not in entry or "chunk_ids" not in entry:
            raise ManifestError(
                f"{ERR_SCHEMA} files['{rel_path}'] missing source_hash or chunk_ids"
            )
        sh = entry["source_hash"]
        ci = entry["chunk_ids"]
        if not isinstance(sh, str):
            raise ManifestError(
                f"{ERR_SCHEMA} files['{rel_path}'].source_hash must be str,"
                f" got {type(sh).__name__}"
            )
        if not isinstance(ci, list) or not all(isinstance(x, str) for x in ci):
            raise ManifestError(
                f"{ERR_SCHEMA} files['{rel_path}'].chunk_ids must be list[str]"
            )
        files[rel_path] = FileEntry(source_hash=sh, chunk_ids=list(ci))

    return Manifest(
        schema_version=sv,
        config_hash=raw["config_hash"],
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        files=files,
    )


def save_manifest(path: Path, m: Manifest) -> None:
    """Atomically write *m* to *path*.

    Uses a sibling ``*.tmp`` file followed by :func:`os.replace`, so a
    crash mid-write leaves the previous manifest byte-identical (or
    absent if there was none).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": m.schema_version,
        "config_hash": m.config_hash,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "files": {
            rel: {"source_hash": e.source_hash, "chunk_ids": list(e.chunk_ids)}
            for rel, e in sorted(m.files.items())
        },
    }
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"

    fd, tmp_name = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, p)
    except BaseException:
        # Clean up the temp file on any failure (including KeyboardInterrupt).
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def manifest_to_dict(m: Manifest) -> dict:
    """Return a plain-dict view of *m* (for tests / debugging)."""
    d = asdict(m)
    return d

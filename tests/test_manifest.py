"""M8 acceptance tests — manifest.

Covers contract criteria 5 and 6.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rag.manifest import (  # noqa: E402
    ERR_INDEX_MISSING,
    ERR_SCHEMA,
    FileEntry,
    Manifest,
    ManifestError,
    load_manifest,
    save_manifest,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_kw: object) -> None:
        raise OSError("network blocked in tests")

    monkeypatch.setattr(socket, "socket", _raise)


def _make_manifest() -> Manifest:
    return Manifest(
        schema_version=1,
        config_hash="cfg-hash-123",
        created_at="2026-05-01T00:00:00+00:00",
        updated_at="2026-05-01T00:00:00+00:00",
        files={
            "a.md": FileEntry(source_hash="h1", chunk_ids=["id1", "id2"]),
            "b.md": FileEntry(source_hash="h2", chunk_ids=[]),
        },
    )


# ---------------------------------------------------------------- criterion 5


def test_load_manifest_missing_raises_index_missing(tmp_path: Path) -> None:
    """Criterion 5a: missing file → [ERR_INDEX_MISSING]."""
    with pytest.raises(ManifestError) as exc:
        load_manifest(tmp_path / "nope.json")
    assert str(exc.value).startswith(ERR_INDEX_MISSING)


def test_load_manifest_malformed_json_raises_schema(tmp_path: Path) -> None:
    """Criterion 5b: malformed JSON → [ERR_SCHEMA]."""
    p = tmp_path / "m.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        load_manifest(p)
    assert str(exc.value).startswith(ERR_SCHEMA)


def test_load_manifest_missing_field_raises_schema(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"schema_version": 1, "files": {}}), encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        load_manifest(p)
    assert str(exc.value).startswith(ERR_SCHEMA)


def test_load_manifest_wrong_files_type_raises_schema(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "config_hash": "h",
                "created_at": "x",
                "updated_at": "y",
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError) as exc:
        load_manifest(p)
    assert str(exc.value).startswith(ERR_SCHEMA)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "data" / "manifest.json"
    m = _make_manifest()
    save_manifest(p, m)
    loaded = load_manifest(p)
    assert loaded.schema_version == 1
    assert loaded.config_hash == "cfg-hash-123"
    assert set(loaded.files.keys()) == {"a.md", "b.md"}
    assert loaded.files["a.md"].chunk_ids == ["id1", "id2"]
    assert loaded.files["b.md"].chunk_ids == []


# ---------------------------------------------------------------- criterion 6


def test_save_manifest_atomic_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 6: os.replace failure leaves prior manifest byte-identical."""
    p = tmp_path / "manifest.json"
    save_manifest(p, _make_manifest())
    original_bytes = p.read_bytes()

    new = Manifest(
        schema_version=1,
        config_hash="updated",
        created_at="2026-05-01",
        updated_at="2026-05-02",
        files={"c.md": FileEntry(source_hash="h3", chunk_ids=["id3"])},
    )

    real_replace = os.replace
    calls = {"n": 0}

    def boom(src, dst):  # noqa: ANN001
        calls["n"] += 1
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save_manifest(p, new)
    monkeypatch.setattr(os, "replace", real_replace)

    # Original bytes preserved.
    assert p.read_bytes() == original_bytes
    # No leftover *.tmp file.
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == [], f"leftover temp files: {leftover}"


def test_save_manifest_first_write_replace_failure_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "manifest.json"
    assert not p.exists()

    def boom(src, dst):  # noqa: ANN001
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save_manifest(p, _make_manifest())
    assert not p.exists()
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_save_manifest_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "nested" / "manifest.json"
    save_manifest(p, _make_manifest())
    assert p.is_file()

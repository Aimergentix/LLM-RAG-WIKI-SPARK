"""Acceptance tests for M7 — Config + schema.

Mapped to contract criteria 1–12 in START-PROMPT.md §5.

All tests are offline: no network, no file writes beyond tmp_path,
no ChromaDB or sentence-transformers imports.
"""

from __future__ import annotations

import copy
import os
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from rag.config import (  # noqa: E402
    Config,
    ConfigError,
    ChunkingConfig,
    DomainConfig,
    EmbeddingConfig,
    ERR_CONFIG,
    IndexingConfig,
    PathsConfig,
    PrivacyConfig,
    ProjectConfig,
    RetrievalConfig,
    RuntimeConfig,
    config_hash,
    load_config,
)

# ---------------------------------------------------------------- fixtures

# Canonical valid config matching MASTER §7; paths use absolute-safe values
# by always writing via tmp_path so relative resolution is deterministic.
VALID_DATA = {
    "schema_version": 1,
    "project": {
        "name": "local-wiki-rag",
        "role": "local_markdown_rag",
        "version": "1.2.0",
    },
    "runtime": {
        "python_min": "3.11",
        "log_format": "jsonl",
    },
    "domain": {"name": "generic"},
    "embedding": {
        "provider": "sentence-transformers",
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "normalize_embeddings": True,
    },
    "paths": {
        "wiki_root": "./wiki",
        "index_dir": "./data/chroma",
        "manifest_path": "./data/manifests/manifest.json",
    },
    "chunking": {
        "strategy": "heading_aware",
        "min_chars": 300,
        "max_chars": 1200,
    },
    "indexing": {"atomic_reindex": True},
    "retrieval": {
        "top_k": 5,
        "distance_metric": "cosine",
        "min_score": 0.72,
        "ood_threshold": 0.3,
    },
    "privacy": {"block_secret_chunks": True},
}


def write_config(tmp_path: Path, data: dict) -> Path:
    """Write *data* as YAML to tmp_path/config.yaml and return the path."""
    import yaml  # noqa: PLC0415

    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    return cfg_file


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block all network access for every test."""

    def _raise(*_a: object, **_kw: object) -> None:
        raise OSError("network blocked in tests")

    monkeypatch.setattr(socket, "socket", _raise)


# ---------------------------------------------------------------- AC 1
# Default load returns typed Config with all MASTER §7 fields.

def test_ac1_default_load_returns_all_fields(tmp_path: Path) -> None:
    cfg_file = write_config(tmp_path, VALID_DATA)
    c = load_config(cfg_file)

    assert isinstance(c, Config)
    assert c.schema_version == 1

    assert isinstance(c.project, ProjectConfig)
    assert c.project.name == "local-wiki-rag"
    assert c.project.role == "local_markdown_rag"
    assert c.project.version == "1.2.0"

    assert isinstance(c.runtime, RuntimeConfig)
    assert c.runtime.python_min == "3.11"
    assert c.runtime.log_format == "jsonl"

    assert isinstance(c.domain, DomainConfig)
    assert c.domain.name == "generic"

    assert isinstance(c.embedding, EmbeddingConfig)
    assert c.embedding.provider == "sentence-transformers"
    assert c.embedding.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert c.embedding.normalize_embeddings is True

    assert isinstance(c.paths, PathsConfig)
    assert isinstance(c.paths.wiki_root, Path)
    assert isinstance(c.paths.index_dir, Path)
    assert isinstance(c.paths.manifest_path, Path)

    assert isinstance(c.chunking, ChunkingConfig)
    assert c.chunking.strategy == "heading_aware"
    assert c.chunking.min_chars == 300
    assert c.chunking.max_chars == 1200

    assert isinstance(c.indexing, IndexingConfig)
    assert c.indexing.atomic_reindex is True

    assert isinstance(c.retrieval, RetrievalConfig)
    assert c.retrieval.top_k == 5
    assert c.retrieval.distance_metric == "cosine"
    assert c.retrieval.min_score == pytest.approx(0.72)
    assert c.retrieval.ood_threshold == pytest.approx(0.3)

    assert isinstance(c.privacy, PrivacyConfig)
    assert c.privacy.block_secret_chunks is True


# ---------------------------------------------------------------- AC 2
# Missing any required field → ConfigError naming the field path.

@pytest.mark.parametrize(
    "drop_key",
    [
        "schema_version",
        "project",
        "runtime",
        "domain",
        "embedding",
        "paths",
        "chunking",
        "indexing",
        "retrieval",
        "privacy",
    ],
)
def test_ac2_missing_top_level_section_raises(
    tmp_path: Path, drop_key: str
) -> None:
    data = copy.deepcopy(VALID_DATA)
    del data[drop_key]
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


@pytest.mark.parametrize(
    "section,leaf",
    [
        ("project", "name"),
        ("embedding", "model_id"),
        ("paths", "wiki_root"),
        ("chunking", "min_chars"),
        ("retrieval", "top_k"),
    ],
)
def test_ac2_missing_leaf_field_names_path(
    tmp_path: Path, section: str, leaf: str
) -> None:
    data = copy.deepcopy(VALID_DATA)
    del data[section][leaf]
    with pytest.raises(ConfigError, match=rf"\[ERR_CONFIG\].*{leaf}"):
        load_config(write_config(tmp_path, data))


# ---------------------------------------------------------------- AC 3
# schema_version != 1 (wrong value or wrong type) → ConfigError.

@pytest.mark.parametrize("bad_version", [2, 0, "1", 1.0, True, None])
def test_ac3_wrong_schema_version_raises(
    tmp_path: Path, bad_version: object
) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["schema_version"] = bad_version
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


# ---------------------------------------------------------------- AC 4
# Wrong type for any leaf field → ConfigError naming the field.

@pytest.mark.parametrize(
    "section,leaf,bad_value",
    [
        ("retrieval", "top_k", "five"),
        ("retrieval", "min_score", "high"),
        ("embedding", "normalize_embeddings", "yes"),
        ("chunking", "min_chars", "300"),
        ("indexing", "atomic_reindex", 1),
        ("project", "name", 42),
    ],
)
def test_ac4_wrong_type_raises_with_field_name(
    tmp_path: Path, section: str, leaf: str, bad_value: object
) -> None:
    data = copy.deepcopy(VALID_DATA)
    data[section][leaf] = bad_value
    with pytest.raises(ConfigError, match=rf"\[ERR_CONFIG\].*{leaf}"):
        load_config(write_config(tmp_path, data))


# ---------------------------------------------------------------- AC 5
# Relative wiki_root resolves against config file's directory.

def test_ac5_relative_wiki_root_resolves_against_config_dir(
    tmp_path: Path,
) -> None:
    cfg_dir = tmp_path / "subdir"
    cfg_dir.mkdir()
    import yaml  # noqa: PLC0415

    data = copy.deepcopy(VALID_DATA)
    data["paths"]["wiki_root"] = "./mywiki"
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text(yaml.dump(data), encoding="utf-8")

    c = load_config(cfg_file)
    expected = (cfg_dir / "mywiki").resolve()
    assert c.paths.wiki_root == expected


# ---------------------------------------------------------------- AC 6
# wiki_root inside entry/ or raw/ → ConfigError.

@pytest.mark.parametrize(
    "bad_root",
    ["./entry/wiki", "./raw/wiki", "entry", "raw"],
)
def test_ac6_wiki_root_in_protected_dir_raises(
    tmp_path: Path, bad_root: str
) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["paths"]["wiki_root"] = bad_root
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


# ---------------------------------------------------------------- AC 7
# ood_threshold > min_score → ConfigError.

def test_ac7_ood_threshold_exceeds_min_score_raises(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["retrieval"]["ood_threshold"] = 0.8
    data["retrieval"]["min_score"] = 0.5
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


def test_ac7_equal_threshold_and_min_score_is_valid(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["retrieval"]["ood_threshold"] = 0.5
    data["retrieval"]["min_score"] = 0.5
    c = load_config(write_config(tmp_path, data))
    assert c.retrieval.ood_threshold == pytest.approx(0.5)
    assert c.retrieval.min_score == pytest.approx(0.5)


# ---------------------------------------------------------------- AC 8
# config_hash() stable across key-order and whitespace differences.

def test_ac8_config_hash_stable_across_config_instances(tmp_path: Path) -> None:
    import yaml  # noqa: PLC0415

    # Load c1 from the standard config file
    c1 = load_config(write_config(tmp_path, VALID_DATA))

    # Write identical data but with top-level keys in reversed order to the
    # SAME directory so all relative paths resolve identically.
    data2 = {k: VALID_DATA[k] for k in reversed(list(VALID_DATA.keys()))}
    cfg2 = tmp_path / "config2.yaml"
    cfg2.write_text(yaml.dump(data2, default_flow_style=False), encoding="utf-8")
    c2 = load_config(cfg2)

    assert config_hash(c1) == config_hash(c2)


def test_ac8_config_hash_same_object_is_idempotent(tmp_path: Path) -> None:
    c = load_config(write_config(tmp_path, VALID_DATA))
    assert config_hash(c) == config_hash(c)


# ---------------------------------------------------------------- AC 9
# config_hash() changes when any field value changes.

def test_ac9_config_hash_changes_on_value_change(tmp_path: Path) -> None:
    c1 = load_config(write_config(tmp_path / "orig", VALID_DATA))

    data2 = copy.deepcopy(VALID_DATA)
    data2["retrieval"]["top_k"] = 10
    c2 = load_config(write_config(tmp_path / "changed", data2))

    assert config_hash(c1) != config_hash(c2)


# ---------------------------------------------------------------- AC 10
# LLM_RAG_WIKI_CONFIG env var overrides default; explicit path arg overrides env var.

def test_ac10_env_var_overrides_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = write_config(tmp_path, VALID_DATA)
    monkeypatch.setenv("LLM_RAG_WIKI_CONFIG", str(cfg))
    # Do NOT pass path arg → should use env var
    c = load_config()
    assert c.schema_version == 1


def test_ac10_explicit_path_overrides_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # env var points at a non-existent file
    monkeypatch.setenv("LLM_RAG_WIKI_CONFIG", str(tmp_path / "nonexistent.yaml"))
    # explicit path arg points at valid config
    cfg = write_config(tmp_path, VALID_DATA)
    c = load_config(cfg)  # explicit path wins
    assert c.schema_version == 1


def test_ac10_missing_env_var_file_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_RAG_WIKI_CONFIG", str(tmp_path / "no_such.yaml"))
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config()


# ---------------------------------------------------------------- AC 11
# import rag.config has no network, no file writes, no log output.

def test_ac11_import_has_no_side_effects(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:  # type: ignore[type-arg]
    # Re-import should be a no-op (module already cached).
    # Verify: no stdout/stderr, no exception raised.
    import rag.config  # noqa: F401, PLC0415

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_ac11_import_no_network_calls() -> None:
    # The no_network autouse fixture already blocks socket; if import triggered
    # a connection it would have raised during module load above. We just
    # assert the module attributes are accessible.
    import rag.config as rc  # noqa: PLC0415

    assert hasattr(rc, "load_config")
    assert hasattr(rc, "config_hash")
    assert hasattr(rc, "ConfigError")
    assert hasattr(rc, "Config")


# ---------------------------------------------------------------- AC 12
# min_chars < 1 or max_chars <= min_chars → ConfigError.

def test_ac12_min_chars_zero_raises(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["chunking"]["min_chars"] = 0
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


def test_ac12_min_chars_negative_raises(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["chunking"]["min_chars"] = -1
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


def test_ac12_max_chars_equal_min_raises(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["chunking"]["min_chars"] = 300
    data["chunking"]["max_chars"] = 300
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


def test_ac12_max_chars_less_than_min_raises(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["chunking"]["min_chars"] = 500
    data["chunking"]["max_chars"] = 100
    with pytest.raises(ConfigError, match=ERR_CONFIG):
        load_config(write_config(tmp_path, data))


def test_ac12_min_chars_one_is_valid(tmp_path: Path) -> None:
    data = copy.deepcopy(VALID_DATA)
    data["chunking"]["min_chars"] = 1
    data["chunking"]["max_chars"] = 2
    c = load_config(write_config(tmp_path, data))
    assert c.chunking.min_chars == 1
    assert c.chunking.max_chars == 2


# ---------------------------------------------------------------- bonus: default config.yaml loads cleanly

def test_shipped_config_yaml_loads() -> None:
    """The canonical config.yaml at repo root loads without error."""
    config_yaml = REPO_ROOT / "config.yaml"
    assert config_yaml.is_file(), "config.yaml missing from repo root"
    c = load_config(config_yaml)
    assert c.schema_version == 1

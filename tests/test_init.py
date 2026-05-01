"""Acceptance tests for M1 — Scaffold + templates.

Mapped to contract criteria 1–7 in START-PROMPT.md §5.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from wiki.init import (  # noqa: E402
    InitError,
    SUPPORTED_PLACEHOLDERS,
    init,
    slugify,
    substitute,
)

PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


# ---- substitute / slugify (golden + unit) ---------------------------------

def test_substitute_resolves_known_placeholders():
    out = substitute("# {{NAME}} — {{DOMAIN}}", {"NAME": "X", "DOMAIN": "D"})
    assert out == "# X — D"


def test_substitute_unknown_placeholder_raises():
    with pytest.raises(KeyError):
        substitute("{{UNKNOWN}}", {})


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"
    assert slugify("Personal Health!") == "personal-health"
    assert slugify("   ") == "wiki"


# ---- criterion 6: project.toml parses + has required keys -----------------

def test_project_toml_valid():
    data = tomllib.loads((REPO_ROOT / "project.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"]
    assert data["project"]["version"]
    assert data["release"]["date"]


# ---- criterion 2 (templates side): every template has ≥1 placeholder ------

@pytest.mark.parametrize(
    "rel",
    [
        "templates/SCHEMA.md",
        "templates/index.md",
        "templates/log.md",
        "templates/CONTEXT.md",
        "templates/pages/source.md",
        "templates/pages/concept.md",
        "templates/pages/entity.md",
        "templates/pages/synthesis.md",
    ],
)
def test_template_contains_placeholder(rel):
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert PLACEHOLDER_RE.search(text), f"{rel} has no {{{{...}}}} token"


# ---- integration: init into tmp dir ---------------------------------------

@pytest.fixture
def fresh_target(tmp_path):
    return tmp_path / "wiki-test"


def test_init_creates_full_tree(fresh_target):
    target = init("Test Domain", "A test domain.", fresh_target, today="2026-04-30")
    # criterion 1: tree
    expected = [
        "entry",
        "raw/assets",
        "wiki/concepts",
        "wiki/entities",
        "wiki/sources",
        "wiki/synthesis",
        ".wiki",
    ]
    for sub in expected:
        assert (target / sub).is_dir(), f"missing {sub}"


def test_init_hydrated_files_have_no_unresolved_placeholders(fresh_target):
    target = init("Test Domain", "A test domain.", fresh_target, today="2026-04-30")
    # criterion 2
    for name in ("SCHEMA.md", "index.md", "log.md"):
        text = (target / name).read_text(encoding="utf-8")
        assert not PLACEHOLDER_RE.search(text), f"{name} has unresolved tokens"
        assert "Test Domain" in text


def test_init_seed_state_files_are_empty_json(fresh_target):
    target = init("Test", "desc", fresh_target, today="2026-04-30")
    # criterion 4
    for name in (".converted.json", ".status.json"):
        path = target / ".wiki" / name
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == {}


# ---- criterion 3: path validation rejects ---------------------------------

def test_init_rejects_existing_path(tmp_path):
    target = tmp_path / "exists"
    target.mkdir()
    with pytest.raises(InitError, match="already exists"):
        init("d", "desc", target)


def test_init_rejects_path_under_dot_git(tmp_path):
    bad = tmp_path / ".git" / "wiki"
    with pytest.raises(InitError, match=".git"):
        init("d", "desc", bad)


def test_init_rejects_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(InitError, match="current working directory"):
        init("d", "desc", tmp_path)


def test_init_rejects_ancestor_of_cwd(tmp_path, monkeypatch):
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    with pytest.raises(InitError, match="ancestor"):
        init("d", "desc", tmp_path / "a")


# ---- criterion 7: re-running on populated path is non-destructive ---------

def test_init_rerun_is_non_destructive(fresh_target):
    target = init("Test", "desc", fresh_target, today="2026-04-30")
    schema_before = (target / "SCHEMA.md").read_text(encoding="utf-8")
    log_before = (target / "log.md").read_text(encoding="utf-8")

    with pytest.raises(InitError):
        init("Test", "desc", fresh_target, today="2026-04-30")

    assert (target / "SCHEMA.md").read_text(encoding="utf-8") == schema_before
    assert (target / "log.md").read_text(encoding="utf-8") == log_before


# ---- criterion 5: scripts/run_phase.sh prints rendered prompt, exits 0 ----

def test_run_phase_renders_prompt():
    script = REPO_ROOT / "scripts" / "run_phase.sh"
    res = subprocess.run(
        [
            "bash",
            str(script),
            "--phase", "P1",
            "--go", "yes",
            "--scope", "x",
            "--deliverables", "y",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip(), "empty stdout"


def test_run_phase_rejects_bad_phase():
    script = REPO_ROOT / "scripts" / "run_phase.sh"
    res = subprocess.run(
        ["bash", str(script), "--phase", "P9", "--go", "yes"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 2

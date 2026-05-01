"""Acceptance tests for M3 — Ingest agent.

Mapped to contract criteria 1–16 in START-PROMPT.md §5.

Test isolation: every test uses ``DeterministicStubAgent`` (or a per-test
spy subclass). The ``no_network`` autouse fixture monkeypatches
``socket.socket`` to raise so a misbehaving agent cannot reach the net.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from wiki import ingest as ingest_mod  # noqa: E402
from wiki.agent_seam import (  # noqa: E402
    Contradiction,
    DeterministicStubAgent,
    IngestAgent,
    TouchedPage,
)
from wiki.ingest import (  # noqa: E402
    EXIT_EXISTS,
    EXIT_OK,
    EXIT_SCHEMA,
    EXIT_SECURITY,
    IngestError,
    ingest_one,
)
from wiki.init import init  # noqa: E402


# ----------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Crit 16: no test path may open a socket."""
    def _boom(*a, **k):
        raise RuntimeError("network forbidden in M3 tests")
    monkeypatch.setattr(socket, "socket", _boom)


@pytest.fixture
def wiki(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return init("Test Domain", "M3 acceptance wiki.", str(tmp_path / "w"))


def _seed_raw(wiki_root: Path, slug: str, body: str = "Hello world.\n",
              converter: str = "copy", status: str = "ok") -> Path:
    """Place a raw page + manifest entry the way M2 would have."""
    raw = wiki_root / "raw" / f"{slug}.md"
    raw.write_text(body, encoding="utf-8")
    mpath = wiki_root / ".wiki" / ".converted.json"
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data[f"entry/{slug}.txt"] = {
        "source": f"entry/{slug}.txt",
        "slug": slug,
        "converter": converter,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "status": status,
        "converted_at": "2026-05-01T00:00:00Z",
    }
    mpath.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return raw


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _stub() -> DeterministicStubAgent:
    return DeterministicStubAgent()


# ---------------------------------------------- crit 1: manifest gate

def test_slug_not_in_manifest_exits_schema(wiki: Path):
    (wiki / "raw" / "ghost.md").write_text("body\n", encoding="utf-8")
    with pytest.raises(IngestError) as ei:
        ingest_one(wiki, "ghost", _stub())
    assert ei.value.exit_code == EXIT_SCHEMA
    assert "manifest" in str(ei.value)
    assert not (wiki / "wiki" / "sources" / "ghost.md").exists()


# ---------------------------------------------- crit 2: source page write

def test_happy_path_writes_source_page(wiki: Path):
    _seed_raw(wiki, "alpha", "# Alpha\n\nFirst point.\nSecond.\nThird.\n",
              converter="pandoc")
    rep = ingest_one(wiki, "alpha", _stub())
    text = rep.source_path.read_text(encoding="utf-8")
    assert "{{" not in text
    assert "type: source" in text
    assert "title: Alpha" in text
    assert "source_path: raw/alpha.md" in text
    assert "converter: pandoc" in text
    assert "## Key Points" in text
    assert "1. First point." in text


# ---------------------------------------------- crit 3: warn-and-stop

def test_existing_source_warn_and_stop_no_other_writes(wiki: Path):
    _seed_raw(wiki, "alpha")
    ingest_one(wiki, "alpha", _stub())
    pre = {p: _sha(wiki / p)
           for p in ("index.md", "log.md", "SCHEMA.md")}
    src_pre = _sha(wiki / "wiki" / "sources" / "alpha.md")
    with pytest.raises(IngestError) as ei:
        ingest_one(wiki, "alpha", _stub())
    assert ei.value.exit_code == EXIT_EXISTS
    for p, h in pre.items():
        assert _sha(wiki / p) == h, f"{p} mutated on warn-and-stop"
    assert _sha(wiki / "wiki" / "sources" / "alpha.md") == src_pre


# ---------------------------------------------- crit 4: --force overwrite

def test_force_overwrites_atomically(wiki: Path):
    _seed_raw(wiki, "alpha", "old body\n")
    ingest_one(wiki, "alpha", _stub())
    _seed_raw(wiki, "alpha", "# Alpha v2\n\nNew point.\n")  # overwrites raw + manifest
    rep = ingest_one(wiki, "alpha", _stub(), force=True)
    text = rep.source_path.read_text(encoding="utf-8")
    assert "title: Alpha v2" in text
    # No tmp leftovers anywhere under wiki_root.
    leftovers = list(wiki.rglob("*.tmp"))
    assert leftovers == []


# ---------------------------------------------- crit 5: deterministic DAG

class _DAGAgent(DeterministicStubAgent):
    def __init__(self, plan):
        self._plan = plan
    def plan_crossrefs(self, **_):
        return self._plan


def test_dag_topo_order_alphabetical_tiebreak(wiki: Path):
    _seed_raw(wiki, "src1")
    plan: list[TouchedPage] = [
        {"kind": "concept", "slug": "a", "title": "A", "depends_on": [], "merge_md": "- a"},
        {"kind": "concept", "slug": "b", "title": "B", "depends_on": ["a"], "merge_md": "- b"},
        {"kind": "concept", "slug": "c", "title": "C", "depends_on": ["a"], "merge_md": "- c"},
        {"kind": "concept", "slug": "d", "title": "D", "depends_on": ["b"], "merge_md": "- d"},
        {"kind": "concept", "slug": "e", "title": "E", "depends_on": [], "merge_md": "- e"},
    ]
    rep = ingest_one(wiki, "src1", _DAGAgent(plan))
    order = [p.stem for p in rep.touched_pages]
    # Pure alphabetical Kahn: at each step take the smallest eligible slug.
    # Start: a,e ready -> a; b,c become ready -> ready={b,c,e}; b -> d ready;
    # ready={c,d,e} -> c -> d -> e.
    assert order == ["a", "b", "c", "d", "e"]


def test_cycle_in_plan_is_schema_error(wiki: Path):
    _seed_raw(wiki, "src1")
    plan: list[TouchedPage] = [
        {"kind": "concept", "slug": "a", "title": "A", "depends_on": ["b"], "merge_md": ""},
        {"kind": "concept", "slug": "b", "title": "B", "depends_on": ["a"], "merge_md": ""},
    ]
    pre_log = _sha(wiki / "log.md")
    with pytest.raises(IngestError) as ei:
        ingest_one(wiki, "src1", _DAGAgent(plan))
    assert ei.value.exit_code == EXIT_SCHEMA
    assert _sha(wiki / "log.md") == pre_log
    assert not (wiki / "wiki" / "sources" / "src1.md").exists()


# ---------------------------------------------- crit 6 / 7: merge create+extend

def test_merge_creates_then_extends(wiki: Path):
    _seed_raw(wiki, "src1")
    plan: list[TouchedPage] = [
        {"kind": "entity", "slug": "alice", "title": "Alice",
         "depends_on": [], "merge_md": "- mentioned in src1"},
    ]
    ingest_one(wiki, "src1", _DAGAgent(plan))
    page = wiki / "wiki" / "entities" / "alice.md"
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    assert "source_count: 1" in text
    assert "- mentioned in src1" in text

    _seed_raw(wiki, "src2", body="another body\n")
    plan2: list[TouchedPage] = [
        {"kind": "entity", "slug": "alice", "title": "Alice",
         "depends_on": [], "merge_md": "- mentioned in src2\n- mentioned in src1"},
    ]
    ingest_one(wiki, "src2", _DAGAgent(plan2))
    text2 = page.read_text(encoding="utf-8")
    assert "source_count: 2" in text2
    # New unique line added.
    assert "- mentioned in src2" in text2
    # Duplicate line not re-added.
    assert text2.count("- mentioned in src1") == 1


# ---------------------------------------------- crit 8: contradictions

class _ContraAgent(DeterministicStubAgent):
    def plan_crossrefs(self, **_):
        return [{
            "kind": "concept", "slug": "topic", "title": "Topic",
            "depends_on": [], "merge_md": "- new framing",
        }]
    def find_contradictions(self, *, page_slug, page_md, new_fragment):
        return [Contradiction(
            with_source_slug="other-src",
            claim="X is true",
            counter_claim="X is false",
        )]


def test_contradictions_inline_format(wiki: Path):
    _seed_raw(wiki, "this-src")
    ingest_one(wiki, "this-src", _ContraAgent())
    text = (wiki / "wiki" / "concepts" / "topic.md").read_text(encoding="utf-8")
    pat = re.compile(
        r"^> ⚠️ Contradiction: \[.+\]\(\.\./sources/.+\.md\) says .+; "
        r"\[.+\]\(\.\./sources/.+\.md\) says .+$",
        re.MULTILINE,
    )
    assert pat.search(text), text


# ---------------------------------------------- crit 9: glossary patcher

class _GlossaryAgent(DeterministicStubAgent):
    def __init__(self, terms):
        self._terms = terms
    def detect_glossary_terms(self, **_):
        return self._terms


def test_glossary_idempotent_and_preserves_manual_rows(wiki: Path):
    # Add a manual row above the eventual auto block.
    schema_path = wiki / "SCHEMA.md"
    schema = schema_path.read_text(encoding="utf-8")
    schema = schema.replace(
        "|  |  |  |\n",
        "|  |  |  |\n| ManualTerm | manual def | none |\n",
        1,
    )
    schema_path.write_text(schema, encoding="utf-8")

    _seed_raw(wiki, "g1")
    ingest_one(wiki, "g1", _GlossaryAgent([("Auto1", "first auto")]))
    snap1 = schema_path.read_text(encoding="utf-8")
    assert "<!-- glossary:auto:start -->" in snap1
    assert "<!-- glossary:auto:end -->" in snap1
    assert "ManualTerm" in snap1

    _seed_raw(wiki, "g2", body="x\n")
    ingest_one(wiki, "g2", _GlossaryAgent([("Auto2", "second auto"),
                                           ("Auto1", "ignored dup")]))
    snap2 = schema_path.read_text(encoding="utf-8")
    # Manual row byte-identical above markers.
    above1 = snap1.split("<!-- glossary:auto:start -->")[0]
    above2 = snap2.split("<!-- glossary:auto:start -->")[0]
    assert above1 == above2
    # Auto1 only present once total.
    assert snap2.count("| Auto1 |") == 1
    assert "Auto2" in snap2


# ---------------------------------------------- crit 10: index updates

def test_index_alphabetical_dedup(wiki: Path):
    _seed_raw(wiki, "src1")
    plan: list[TouchedPage] = [
        {"kind": "concept", "slug": "zeta", "title": "Zeta",
         "depends_on": [], "merge_md": ""},
        {"kind": "concept", "slug": "alpha", "title": "Alpha",
         "depends_on": [], "merge_md": ""},
    ]
    ingest_one(wiki, "src1", _DAGAgent(plan))
    idx = (wiki / "index.md").read_text(encoding="utf-8")
    a = idx.find("wiki/concepts/alpha.md")
    z = idx.find("wiki/concepts/zeta.md")
    assert 0 < a < z, idx
    # Re-run with --force; entries not duplicated.
    ingest_one(wiki, "src1", _DAGAgent(plan), force=True)
    idx2 = (wiki / "index.md").read_text(encoding="utf-8")
    assert idx2.count("wiki/sources/src1.md") == 1
    assert idx2.count("wiki/concepts/alpha.md") == 1


# ---------------------------------------------- crit 11: log append

def test_log_append_format_and_count(wiki: Path):
    _seed_raw(wiki, "src1", body="# Title One\n\nfoo\nbar\nbaz\n")
    plan: list[TouchedPage] = [
        {"kind": "concept", "slug": "c1", "title": "C1",
         "depends_on": [], "merge_md": ""},
        {"kind": "entity", "slug": "e1", "title": "E1",
         "depends_on": [], "merge_md": ""},
    ]
    ingest_one(wiki, "src1", _DAGAgent(plan))
    log = (wiki / "log.md").read_text(encoding="utf-8")
    pat = re.compile(
        r"^## \[\d{4}-\d{2}-\d{2}\] ingest \| Title One \| sources/src1\.md "
        r"\| 3 pages touched$",
        re.MULTILINE,
    )
    assert pat.search(log), log


# ---------------------------------------------- crit 12: atomicity

def test_atomic_replace_failure_leaves_targets_unchanged(wiki: Path, monkeypatch):
    _seed_raw(wiki, "src1", body="# Hello\n\nfirst\nsecond\nthird\n")
    targets = [
        wiki / "index.md", wiki / "log.md", wiki / "SCHEMA.md",
    ]
    pre = {p: _sha(p) for p in targets}

    def _boom(_a, _b):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(ingest_mod.os, "replace", _boom)

    with pytest.raises(OSError):
        ingest_one(wiki, "src1", _stub())

    for p, h in pre.items():
        assert _sha(p) == h, f"{p} changed despite replace failure"
    assert not (wiki / "wiki" / "sources" / "src1.md").exists()
    # Temps cleaned up.
    assert list(wiki.rglob("*.tmp")) == []


# ---------------------------------------------- crit 13: needs-vision

class _VisionAgent(DeterministicStubAgent):
    def __init__(self):
        self.calls = []
    def resolve_vision(self, *, marker_path, asset_path):
        self.calls.append((marker_path, asset_path))
        return "VISION-RESOLVED-TEXT"
    def extract_takeaways(self, *, raw_md, schema_md, index_md):
        # Verify vision text is fed in.
        assert "VISION-RESOLVED-TEXT" in raw_md
        return ["v1", "v2", "v3"]


def test_needs_vision_passthrough_no_raw_mutation(wiki: Path):
    body = "<!-- needs-vision: /tmp/x.png -->\nremaining body\n"
    raw = _seed_raw(wiki, "scan", body=body, converter="vision",
                    status="needs_vision")
    raw_pre = _sha(raw)
    manifest_pre = _sha(wiki / ".wiki" / ".converted.json")

    agent = _VisionAgent()
    ingest_one(wiki, "scan", agent)

    assert agent.calls, "resolve_vision was not invoked"
    assert _sha(raw) == raw_pre
    assert _sha(wiki / ".wiki" / ".converted.json") == manifest_pre


# ---------------------------------------------- crit 14: path safety

@pytest.mark.parametrize("bad", ["../etc/passwd", "foo/bar", ".."])
def test_bad_slug_rejected(wiki: Path, bad: str):
    with pytest.raises(IngestError) as ei:
        ingest_one(wiki, bad, _stub())
    assert ei.value.exit_code == EXIT_SECURITY


def test_symlink_under_raw_not_followed(wiki: Path, tmp_path: Path):
    target = tmp_path / "outside.md"
    target.write_text("evil\n", encoding="utf-8")
    link = wiki / "raw" / "evil.md"
    link.symlink_to(target)
    # Manifest entry exists but path is a symlink.
    mpath = wiki / ".wiki" / ".converted.json"
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["entry/evil.txt"] = {
        "source": "entry/evil.txt", "slug": "evil",
        "converter": "copy", "sha256": "x", "status": "ok",
        "converted_at": "2026-05-01T00:00:00Z",
    }
    mpath.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(IngestError) as ei:
        ingest_one(wiki, "evil", _stub())
    assert ei.value.exit_code == EXIT_SCHEMA  # symlink rejected as not-a-file


# ---------------------------------------------- crit 15: read-only upstreams

def test_no_writes_under_readonly_dirs(wiki: Path):
    raw = _seed_raw(wiki, "src1", body="# T\n\na\nb\nc\n")
    raw_pre = _sha(raw)
    entry_dir = wiki / "entry"
    manifest = wiki / ".wiki" / ".converted.json"
    entry_pre = sorted(p.name for p in entry_dir.iterdir())
    manifest_pre = _sha(manifest)

    ingest_one(wiki, "src1", _stub())

    assert _sha(raw) == raw_pre
    assert sorted(p.name for p in entry_dir.iterdir()) == entry_pre
    assert _sha(manifest) == manifest_pre


# ---------------------------------------------- CLI smoke (env stub binding)

def test_cli_requires_agent_binding(wiki: Path, monkeypatch):
    _seed_raw(wiki, "src1", body="# T\n\na\nb\nc\n")
    monkeypatch.delenv("LLMWIKI_TEST_STUB_AGENT", raising=False)
    env = {**os.environ}
    env.pop("LLMWIKI_TEST_STUB_AGENT", None)
    r = subprocess.run(
        [sys.executable, "-m", "wiki.ingest", "src1",
         "--wiki-root", str(wiki)],
        capture_output=True, text=True,
        env={**env, "PYTHONPATH": str(SRC)},
    )
    assert r.returncode == 5, r.stderr
    assert "no agent bound" in r.stderr


def test_cli_with_stub_env(wiki: Path):
    _seed_raw(wiki, "src1", body="# T\n\na\nb\nc\n")
    r = subprocess.run(
        [sys.executable, "-m", "wiki.ingest", "src1",
         "--wiki-root", str(wiki)],
        capture_output=True, text=True,
        env={**os.environ,
             "PYTHONPATH": str(SRC),
             "LLMWIKI_TEST_STUB_AGENT": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert "INGEST COMPLETE" in r.stdout

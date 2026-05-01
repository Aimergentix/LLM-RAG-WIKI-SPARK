"""Acceptance tests for M5 — Query + synthesis.

Mapped to contract criteria 1–18 in START-PROMPT.md §5.

Test isolation: every test uses ``DeterministicStubQueryAgent`` (or a
per-test subclass). The ``no_network`` autouse fixture monkeypatches
``socket.socket`` to raise so no misbehaving agent can reach the net.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from wiki.init import init  # noqa: E402
from wiki.query import (  # noqa: E402
    EXIT_EXISTS,
    EXIT_OK,
    EXIT_RUNTIME,
    EXIT_SCHEMA,
    EXIT_SECURITY,
    QueryError,
    QueryReport,
    slugify_question,
    query_one,
)
from wiki.query_agent import (  # noqa: E402
    DeterministicStubQueryAgent,
    PageSummary,
    QueryAgent,
    SynthesisResult,
)


# ----------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Crit 16: no test may open a socket."""
    def _boom(*a, **k):
        raise RuntimeError("network forbidden in M5 tests")
    monkeypatch.setattr(socket, "socket", _boom)


@pytest.fixture
def wiki(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return init("Test Domain", "M5 acceptance wiki.", str(tmp_path / "w"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _stub() -> DeterministicStubQueryAgent:
    return DeterministicStubQueryAgent()


def _seed_page(wiki_root: Path, kind: str, slug: str, body: str = "") -> Path:
    """Plant a wiki page so the query has something to find."""
    d = wiki_root / "wiki" / kind
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{slug}.md"
    content = f"---\ntype: {kind}\nupdated: 2026-05-01\n---\n\n# {slug.title()}\n\n{body}\n"
    p.write_text(content, encoding="utf-8")
    return p


# ------------------------------------------------ crit 1: wiki root gate

def test_wiki_root_gate_missing_index(tmp_path: Path, monkeypatch):
    """query_one against a path missing index.md raises QueryError [ERR_SCHEMA]."""
    monkeypatch.chdir(tmp_path)
    root = init("D", "desc", str(tmp_path / "w"))
    (root / "index.md").unlink()
    with pytest.raises(QueryError) as ei:
        query_one(root, "anything", _stub())
    assert ei.value.exit_code == EXIT_SCHEMA
    assert "[ERR_SCHEMA]" in str(ei.value)


def test_wiki_root_gate_missing_converted_json(tmp_path: Path, monkeypatch):
    """query_one against a path missing .wiki/.converted.json raises [ERR_SCHEMA]."""
    monkeypatch.chdir(tmp_path)
    root = init("D", "desc", str(tmp_path / "w"))
    (root / ".wiki" / ".converted.json").unlink()
    with pytest.raises(QueryError) as ei:
        query_one(root, "anything", _stub())
    assert ei.value.exit_code == EXIT_SCHEMA


# ------------------------------------------------ crit 2: empty wiki

def test_empty_wiki_graceful(wiki: Path):
    """query_one on a fresh scaffold succeeds; sources_read=[]; no synthesis written."""
    rep = query_one(wiki, "What is known?", _stub())
    assert isinstance(rep.answer, str) and rep.answer
    assert rep.sources_read == []
    assert rep.synthesis_path is None
    assert not list((wiki / "wiki" / "synthesis").rglob("*.md"))


# ------------------------------------------------ crit 3: no filing

def test_answer_without_filing(wiki: Path):
    """Without --file, synthesis_path=None; index.md unchanged; one 'not filed' log line."""
    _seed_page(wiki, "concepts", "foo", "Something about foo.")
    pre_index = _sha(wiki / "index.md")
    rep = query_one(wiki, "Tell me about foo", _stub())
    assert rep.synthesis_path is None
    assert _sha(wiki / "index.md") == pre_index
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert "not filed" in log
    assert "filed as synthesis/" not in log


# ------------------------------------------------ crit 4: valid synthesis page

def test_filing_writes_valid_synthesis_page(wiki: Path):
    """With file_as_synthesis=True, synthesis page has valid frontmatter and sections."""
    _seed_page(wiki, "concepts", "bar", "Bar is important.")
    rep = query_one(wiki, "What is bar?", _stub(), file_as_synthesis=True)
    assert rep.synthesis_path is not None
    assert rep.synthesis_path.exists()
    text = rep.synthesis_path.read_text(encoding="utf-8")
    assert "{{" not in text
    assert "type: synthesis" in text
    assert "question:" in text
    assert "created:" in text
    assert "## Answer" in text
    assert "## Sources Consulted" in text
    assert "## Confidence" in text
    assert "## Follow-up Questions" in text


# ------------------------------------------------ crit 5: sources_read frontmatter

def test_sources_read_frontmatter_matches_agent(wiki: Path):
    """sources_read in frontmatter matches SynthesisResult.sources_read."""
    _seed_page(wiki, "concepts", "c1", "Content c1.")
    _seed_page(wiki, "entities", "e1", "Content e1.")

    rep = query_one(wiki, "Tell me everything", _stub(), file_as_synthesis=True)
    assert rep.synthesis_path is not None
    text = rep.synthesis_path.read_text(encoding="utf-8")

    from wiki import _frontmatter as fm_mod
    fm_data, _, _ = fm_mod.split(text)
    assert fm_data.get("sources_read") == rep.sources_read


# ------------------------------------------------ crit 6: warn-and-stop

def test_pre_existing_warn_and_stop(wiki: Path):
    """Pre-existing synthesis without --force → exit EXISTS; index.md and log.md unchanged."""
    query_one(wiki, "Q?", _stub(), file_as_synthesis=True, slug="q")
    pre_index = _sha(wiki / "index.md")
    pre_log = _sha(wiki / "log.md")
    pre_synth = _sha(wiki / "wiki" / "synthesis" / "q.md")
    with pytest.raises(QueryError) as ei:
        query_one(wiki, "Q?", _stub(), file_as_synthesis=True, slug="q")
    assert ei.value.exit_code == EXIT_EXISTS
    assert _sha(wiki / "index.md") == pre_index
    assert _sha(wiki / "log.md") == pre_log
    assert _sha(wiki / "wiki" / "synthesis" / "q.md") == pre_synth


# ------------------------------------------------ crit 7: --force overwrite

def test_force_overwrites_atomically(wiki: Path):
    """--force rewrites synthesis page; no *.tmp left; index not duplicated."""
    query_one(wiki, "What is X?", _stub(), file_as_synthesis=True, slug="what-is-x")
    query_one(wiki, "What is X?", _stub(), file_as_synthesis=True, slug="what-is-x", force=True)
    leftovers = list(wiki.rglob("*.tmp"))
    assert leftovers == []
    index_text = (wiki / "index.md").read_text(encoding="utf-8")
    assert index_text.count("what-is-x.md") == 1


# ------------------------------------------------ crit 8: index Synthesis section

def test_index_synthesis_section_updated(wiki: Path):
    """Synthesis slug appears under ## Synthesis in index.md after filing."""
    query_one(wiki, "Why?", _stub(), file_as_synthesis=True, slug="why")
    index_text = (wiki / "index.md").read_text(encoding="utf-8")
    assert "## Synthesis" in index_text
    assert "why.md" in index_text


# ------------------------------------------------ crit 9: index section created if absent

def test_index_synthesis_section_appended_when_missing(wiki: Path):
    """If index.md has no ## Synthesis section, it is appended; prior content byte-identical."""
    index_path = wiki / "index.md"
    original = index_path.read_text(encoding="utf-8")
    # Remove existing ## Synthesis section if present.
    cleaned = re.sub(r"\n## Synthesis\b.*", "", original, flags=re.DOTALL).rstrip("\n") + "\n"
    index_path.write_text(cleaned, encoding="utf-8")
    prefix_before = (wiki / "index.md").read_text(encoding="utf-8")

    query_one(wiki, "New question", _stub(), file_as_synthesis=True, slug="new-question")
    after = (wiki / "index.md").read_text(encoding="utf-8")
    assert "## Synthesis" in after
    assert "new-question.md" in after
    # The portion before ## Synthesis must be unchanged.
    # split_point is the index of \n that precedes "## Synthesis".
    # after[:split_point] == prefix_before (which ends with \n).
    split_point = after.index("\n## Synthesis")
    assert after[:split_point] == prefix_before


# ------------------------------------------------ crit 10: log format

_LOG_FILED_RE = re.compile(
    r"^## \[\d{4}-\d{2}-\d{2}\] query \| .{1,80} \| filed as synthesis/[a-z0-9_-]+\.md$",
    re.MULTILINE,
)
_LOG_UNFILED_RE = re.compile(
    r"^## \[\d{4}-\d{2}-\d{2}\] query \| .{1,80} \| not filed$",
    re.MULTILINE,
)


def test_log_format_filed(wiki: Path):
    query_one(wiki, "A filed query", _stub(), file_as_synthesis=True, slug="filed-q")
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert _LOG_FILED_RE.search(log), f"filed log line not found in:\n{log}"


def test_log_format_unfiled(wiki: Path):
    query_one(wiki, "An unfiled query", _stub())
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert _LOG_UNFILED_RE.search(log), f"unfiled log line not found in:\n{log}"


# ------------------------------------------------ crit 11: atomicity

def test_atomicity_on_replace_failure(wiki: Path, monkeypatch):
    """If os.replace raises mid-run, all target files remain byte-identical."""
    pre_index = _sha(wiki / "index.md")
    pre_log = _sha(wiki / "log.md")

    call_count = [0]
    real_replace = os.replace

    def _fail_replace(src, dst):
        call_count[0] += 1
        if call_count[0] >= 1:
            raise OSError("injected replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _fail_replace)

    with pytest.raises(OSError):
        query_one(wiki, "Atomic?", _stub(), file_as_synthesis=True, slug="atomic")

    # No *.tmp leftovers.
    assert list(wiki.rglob("*.tmp")) == []
    # Target files unchanged.
    assert _sha(wiki / "index.md") == pre_index
    assert _sha(wiki / "log.md") == pre_log
    assert not (wiki / "wiki" / "synthesis" / "atomic.md").exists()


# ------------------------------------------------ crit 12: slug auto-derivation

def test_slug_auto_derivation():
    """slugify_question produces a valid slug ≤64 chars."""
    q = "What is the relationship between concept-A and entity-B?"
    s = slugify_question(q)
    assert re.match(r"^[a-z0-9][a-z0-9_-]{0,127}$", s)
    assert len(s) <= 64
    assert "/" not in s
    assert ".." not in s


def test_slug_auto_derivation_empty_input():
    """Empty question falls back to 'query'."""
    assert slugify_question("") == "query"
    assert slugify_question("   ") == "query"


def test_slug_used_in_filename(wiki: Path):
    """Agent's propose_slug result is used as the synthesis filename stem."""
    rep = query_one(wiki, "Hello world", _stub(), file_as_synthesis=True)
    assert rep.synthesis_path is not None
    # DeterministicStubQueryAgent.propose_slug("Hello world") -> "hello-world"
    assert rep.synthesis_path.stem == "hello-world"


# ------------------------------------------------ crit 13: custom slug validation

def test_custom_slug_with_slash_raises_security(wiki: Path):
    """Slug containing '/' → [ERR_SECURITY] exit 4."""
    with pytest.raises(QueryError) as ei:
        query_one(wiki, "Q", _stub(), file_as_synthesis=True, slug="../../etc/passwd")
    assert ei.value.exit_code == EXIT_SECURITY


def test_custom_slug_with_dotdot_raises_security(wiki: Path):
    """Slug containing '..' → [ERR_SECURITY] exit 4."""
    with pytest.raises(QueryError) as ei:
        query_one(wiki, "Q", _stub(), file_as_synthesis=True, slug="..bad")
    assert ei.value.exit_code == EXIT_SECURITY


# ------------------------------------------------ crit 14: symlink wiki root

def test_symlink_wiki_root_raises_security(wiki: Path, tmp_path: Path):
    """Wiki root passed as a symlink → [ERR_SECURITY] exit 4."""
    link = tmp_path / "wiki_link"
    link.symlink_to(wiki)
    with pytest.raises(QueryError) as ei:
        query_one(link, "Q", _stub())
    assert ei.value.exit_code == EXIT_SECURITY


# ------------------------------------------------ crit 15: read-only upstreams

def test_read_only_upstreams(wiki: Path):
    """After any run, raw/, entry/, .wiki/ and legacy folders are untouched."""
    # Record tree sha of protected dirs.
    def _tree_sha(d: Path) -> str:
        h = hashlib.sha256()
        for p in sorted(d.rglob("*")):
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()

    protected = [wiki / "raw", wiki / "entry", wiki / ".wiki"]
    pre = {str(d): _tree_sha(d) for d in protected if d.exists()}

    query_one(wiki, "Protected?", _stub(), file_as_synthesis=True, slug="protected")

    for d_str, before in pre.items():
        after = _tree_sha(Path(d_str))
        assert before == after, f"{d_str} mutated"


# ------------------------------------------------ crit 16: no network (autouse)
# Covered by the no_network autouse fixture applied to every test.


# ------------------------------------------------ crit 17: LLMWIKI_TEST_STUB_AGENT=1

def test_cli_uses_stub_under_env_var(wiki: Path, monkeypatch):
    """CLI without --agent uses DeterministicStubQueryAgent under LLMWIKI_TEST_STUB_AGENT=1."""
    monkeypatch.setenv("LLMWIKI_TEST_STUB_AGENT", "1")
    import wiki.query as query_mod
    rc = query_mod.main(
        [str("What?"), "--wiki-root", str(wiki), "--slug", "env-stub"]
    )
    assert rc == EXIT_OK


# ------------------------------------------------ crit 18: no-agent rejection

def test_cli_no_agent_no_env_var_exits_runtime(wiki: Path, monkeypatch):
    """CLI without --agent and without env var exits 5 [ERR_RUNTIME], writes nothing."""
    monkeypatch.delenv("LLMWIKI_TEST_STUB_AGENT", raising=False)
    pre_log = _sha(wiki / "log.md")
    import wiki.query as query_mod
    rc = query_mod.main(["What?", "--wiki-root", str(wiki)])
    assert rc == EXIT_RUNTIME
    assert _sha(wiki / "log.md") == pre_log


# ------------------------------------------------ integration: init → query → file

def test_integration_init_seed_query_file(tmp_path: Path, monkeypatch):
    """End-to-end: init a wiki, seed two pages, run query_one with filing, check coherence."""
    monkeypatch.chdir(tmp_path)
    root = init("Integration Domain", "Integration test wiki.", str(tmp_path / "integ"))

    _seed_page(root, "concepts", "alpha", "Alpha concept body.")
    _seed_page(root, "entities", "beta", "Beta entity body.")

    rep = query_one(
        root, "What is alpha and beta?", _stub(), file_as_synthesis=True
    )
    assert rep.synthesis_path is not None
    assert rep.synthesis_path.exists()

    # Index updated.
    index_text = (root / "index.md").read_text(encoding="utf-8")
    assert rep.synthesis_path.stem in index_text

    # Log updated.
    log_text = (root / "log.md").read_text(encoding="utf-8")
    assert "filed as synthesis/" in log_text

    # Frontmatter valid.
    from wiki import _frontmatter as fm_mod
    synth_text = rep.synthesis_path.read_text(encoding="utf-8")
    fm_data, _, _ = fm_mod.split(synth_text)
    assert fm_data.get("type") == "synthesis"
    assert fm_data.get("question") == "What is alpha and beta?"
    assert "{{" not in synth_text

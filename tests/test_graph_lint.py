"""Acceptance tests for M4 — Graph lint.

Mapped to contract criteria 1–16 in START-PROMPT.md §5.
"""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import time
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

from wiki import graph_lint as gl  # noqa: E402
from wiki.graph_lint import (  # noqa: E402
    EXIT_FAIL,
    EXIT_OK,
    EXIT_SCHEMA,
    EXIT_SECURITY,
    LOG_LINE_RE,
    SchemaError,
    SecurityError,
    lint_wiki,
    main,
)
from wiki.init import init  # noqa: E402


# ----------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Crit 16: no test path may open a socket."""
    def _boom(*a, **k):
        raise RuntimeError("network forbidden in M4 tests")
    monkeypatch.setattr(socket, "socket", _boom)


@pytest.fixture
def wiki(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return init("Test Domain", "M4 acceptance wiki.", str(tmp_path / "w"))


# ----------------------------------------------------------------- helpers

def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _page(slug: str, kind: str = "concept", *, body: str = "",
          meta_extra: str = "") -> str:
    return (
        f"---\ntype: {kind}\ntitle: {slug.title()}\nslug: {slug}\n"
        f"{meta_extra}---\n\n# {slug.title()}\n\n{body}\n"
    )


def _tree_hash(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
    return out


# --------------------------------------------------------------- crit 1: empty

def test_empty_wiki(wiki: Path):
    r = lint_wiki(wiki)
    assert r.pages == 0
    assert r.edges == 0
    assert r.discourse_state == "EMPTY"
    assert r.issues == []


# ------------------------------------------------------------- crit 2: stdlib

def test_pure_stdlib():
    src = (REPO_ROOT / "src/wiki/graph_lint.py").read_text()
    for forbidden in (
        "import networkx", "import yaml", "import requests",
        "from networkx", "from yaml", "from requests",
    ):
        assert forbidden not in src


# -------------------------------------------------------------- crit 3: speed

def test_speed_200_pages(wiki: Path):
    concepts = wiki / "wiki/concepts"
    for i in range(200):
        slug = f"c{i:03d}"
        targets = [(i + 1) % 200, (i + 2) % 200, (i + 3) % 200]
        body = "\n".join(
            f"- [c{t:03d}](c{t:03d}.md) — relatedTo: x" for t in targets
        )
        _write(concepts / f"{slug}.md", _page(slug, body=body))
    idx = "\n".join(
        f"- [{f.stem}](wiki/concepts/{f.name})"
        for f in sorted(concepts.glob("*.md"))
    )
    (wiki / "index.md").write_text(idx + "\n", encoding="utf-8")
    t0 = time.monotonic()
    r = lint_wiki(wiki)
    elapsed = time.monotonic() - t0
    assert r.pages == 200
    assert r.edges == 600
    assert elapsed < 3.0, f"slow: {elapsed:.2f}s"


# ---------------------------------------------------------- crit 4: read-only

def test_read_only(wiki: Path):
    _write(wiki / "wiki/concepts/a.md", _page("a"))
    _write(wiki / "wiki/concepts/b.md", _page("b", body="[a](a.md)"))
    before = _tree_hash(wiki)
    lint_wiki(wiki)
    after = _tree_hash(wiki)
    assert before == after


# ----------------------------------------------------------- crit 5: --log

def test_log_append(wiki: Path):
    _write(wiki / "wiki/concepts/a.md", _page("a"))
    log_before = (wiki / "log.md").read_text(encoding="utf-8")
    rc = main([str(wiki), "--log", "--fail-on=none"])
    assert rc == EXIT_OK
    log_after = (wiki / "log.md").read_text(encoding="utf-8")
    assert log_after.startswith(log_before)
    new = log_after[len(log_before):]
    new_stripped = new.lstrip("\n").rstrip("\n")
    assert "\n" not in new_stripped, f"multi-line append: {new!r}"
    assert LOG_LINE_RE.match(new_stripped), new_stripped


# ---------------------------------------------------------- crit 6: orphan

def test_orphan_rule(wiki: Path):
    _write(wiki / "wiki/concepts/lonely.md", _page("lonely"))
    r = lint_wiki(wiki)
    orphans = [i for i in r.issues if i["rule"] == "orphan"]
    assert len(orphans) == 1
    assert orphans[0]["severity"] == "high"
    assert orphans[0]["page"] == "wiki/concepts/lonely.md"


def test_orphan_exempts_sources(wiki: Path):
    _write(wiki / "wiki/sources/some.md", _page("some", kind="raw_source"))
    r = lint_wiki(wiki)
    assert not any(i["rule"] == "orphan" for i in r.issues)


# ------------------------------------------------------- crit 7: broken_link

def test_broken_link_rule(wiki: Path):
    _write(
        wiki / "wiki/concepts/a.md",
        _page("a", body="See [missing](missing.md)."),
    )
    r = lint_wiki(wiki)
    broken = [i for i in r.issues if i["rule"] == "broken_link"]
    assert len(broken) == 1
    assert broken[0]["severity"] == "high"
    assert "missing.md" in broken[0]["target"]


def test_link_to_raw_not_flagged(wiki: Path):
    _write(
        wiki / "wiki/concepts/a.md",
        _page("a", body="See [src](../../raw/x.md)."),
    )
    r = lint_wiki(wiki)
    assert not any(i["rule"] == "broken_link" for i in r.issues)


# -------------------------------------------------------- crit 8: index_gap

def test_index_gap_rule(wiki: Path):
    _write(wiki / "wiki/concepts/a.md", _page("a"))
    r = lint_wiki(wiki)
    assert any(
        i["rule"] == "index_gap" and i["page"] == "wiki/concepts/a.md"
        for i in r.issues
    )


def test_index_gap_clears_when_listed(wiki: Path):
    _write(wiki / "wiki/concepts/a.md", _page("a"))
    idx_path = wiki / "index.md"
    idx_path.write_text(
        idx_path.read_text(encoding="utf-8")
        + "\n- [a](wiki/concepts/a.md)\n",
        encoding="utf-8",
    )
    r = lint_wiki(wiki)
    assert not any(i["rule"] == "index_gap" for i in r.issues)


# --------------------------------------------------- crit 9: hub_and_spoke

def test_hub_and_spoke_rule(wiki: Path):
    _write(wiki / "wiki/concepts/hub.md", _page("hub"))
    for s in ("a", "b", "c", "d", "e"):
        _write(
            wiki / f"wiki/concepts/{s}.md",
            _page(s, body="[h](hub.md)"),
        )
    r = lint_wiki(wiki)
    hub = [i for i in r.issues if i["rule"] == "hub_and_spoke"]
    assert hub, "expected hub_and_spoke flag"
    assert hub[0]["severity"] == "medium"
    assert hub[0]["page"] == "wiki/concepts/hub.md"


def test_balanced_no_hub(wiki: Path):
    pages = ["a", "b", "c", "d", "e"]
    for i, s in enumerate(pages):
        nxt = pages[(i + 1) % len(pages)]
        _write(
            wiki / f"wiki/concepts/{s}.md",
            _page(s, body=f"[{nxt}]({nxt}.md)"),
        )
    r = lint_wiki(wiki)
    assert not any(i["rule"] == "hub_and_spoke" for i in r.issues)


# --------------------------------------------------- crit 10: relation codes

def test_relation_code_distribution(wiki: Path):
    bullets: list[str] = []
    for i in range(9):
        bullets.append(f"- [t{i}](t{i}.md) — relatedTo: foo")
    for i in range(3):
        bullets.append(f"- [u{i}](u{i}.md) — isA: bar")
    body = "## Cross-References\n" + "\n".join(bullets) + "\n"
    _write(wiki / "wiki/concepts/big.md", _page("big", body=body))
    r = lint_wiki(wiki)
    assert any(
        i["rule"] == "relation_code_distribution" for i in r.issues
    )


def test_unknown_relation_code(wiki: Path):
    body = (
        "## Cross-References\n"
        "- [x](x.md) — kindaLike: foo\n"
    )
    _write(wiki / "wiki/concepts/p.md", _page("p", body=body))
    r = lint_wiki(wiki)
    unk = [i for i in r.issues if i["rule"] == "unknown_relation_code"]
    assert unk
    assert unk[0]["severity"] == "low"
    assert "kindaLike" in unk[0]["message"]


def test_relation_distribution_below_min_sample(wiki: Path):
    bullets = ["- [t0](t0.md) — relatedTo: foo"] * 5
    body = "## Cross-References\n" + "\n".join(bullets) + "\n"
    _write(wiki / "wiki/concepts/p.md", _page("p", body=body))
    r = lint_wiki(wiki)
    assert not any(
        i["rule"] == "relation_code_distribution" for i in r.issues
    )


# ----------------------------------------------------- crit 11: stale

def test_stale_candidate(wiki: Path):
    _write(
        wiki / "wiki/concepts/old.md",
        _page("old", meta_extra="updated: 2020-01-01\n"),
    )
    r = lint_wiki(wiki)
    stale = [i for i in r.issues if i["rule"] == "stale_candidate"]
    assert stale
    assert stale[0]["severity"] == "low"


def test_fresh_not_stale(wiki: Path):
    today = date.today().isoformat()
    _write(
        wiki / "wiki/concepts/fresh.md",
        _page("fresh", meta_extra=f"updated: {today}\n"),
    )
    r = lint_wiki(wiki)
    assert not any(i["rule"] == "stale_candidate" for i in r.issues)


# -------------------------------------------------- crit 12: asymmetric

def test_asymmetric_coverage(wiki: Path):
    for i in range(10):
        _write(
            wiki / f"wiki/concepts/c{i}.md",
            _page(f"c{i}", kind="concept"),
        )
    _write(wiki / "wiki/entities/e0.md", _page("e0", kind="entity"))
    r = lint_wiki(wiki)
    assert any(i["rule"] == "asymmetric_coverage" for i in r.issues)


def test_balanced_coverage(wiki: Path):
    for i in range(5):
        _write(
            wiki / f"wiki/concepts/c{i}.md",
            _page(f"c{i}", kind="concept"),
        )
        _write(
            wiki / f"wiki/entities/e{i}.md",
            _page(f"e{i}", kind="entity"),
        )
    r = lint_wiki(wiki)
    assert not any(i["rule"] == "asymmetric_coverage" for i in r.issues)


# --------------------------------------------- crit 13: discourse states

def test_discourse_empty(wiki: Path):
    assert lint_wiki(wiki).discourse_state == "EMPTY"


def test_discourse_biased(wiki: Path):
    _write(wiki / "wiki/concepts/hub.md", _page("hub"))
    for s in ("a", "b", "c", "d", "e"):
        _write(
            wiki / f"wiki/concepts/{s}.md",
            _page(s, body="[h](hub.md)"),
        )
    assert lint_wiki(wiki).discourse_state == "BIASED"


def test_discourse_focused(wiki: Path):
    chain = ["a", "b", "c", "d", "e"]
    for i in range(len(chain) - 1):
        _write(
            wiki / f"wiki/concepts/{chain[i]}.md",
            _page(chain[i], body=f"[next]({chain[i + 1]}.md)"),
        )
    _write(
        wiki / f"wiki/concepts/{chain[-1]}.md",
        _page(chain[-1]),
    )
    assert lint_wiki(wiki).discourse_state == "FOCUSED"


def test_discourse_dispersed(wiki: Path):
    for s in ("a", "b", "c", "d", "e", "f"):
        _write(wiki / f"wiki/concepts/{s}.md", _page(s))
    assert lint_wiki(wiki).discourse_state == "DISPERSED"


def test_discourse_diversified(wiki: Path):
    ring1 = {"a": "b", "b": "c", "c": "a"}
    ring2 = {"d": "e", "e": "f", "f": "d"}
    for s, nxt in {**ring1, **ring2}.items():
        _write(
            wiki / f"wiki/concepts/{s}.md",
            _page(s, body=f"[n]({nxt}.md)"),
        )
    assert lint_wiki(wiki).discourse_state == "DIVERSIFIED"


# --------------------------------------------------------- crit 14: JSON

def test_json_output(wiki: Path, capsys):
    _write(wiki / "wiki/concepts/a.md", _page("a"))
    rc = main([str(wiki), "--json", "--fail-on=none"])
    assert rc == EXIT_OK
    out = capsys.readouterr().out
    obj = json.loads(out)
    assert obj["pages"] == 1
    assert "issues" in obj
    assert obj["discourse_state"] in (
        "EMPTY", "BIASED", "FOCUSED", "DIVERSIFIED", "DISPERSED"
    )


# --------------------------------------------------- crit 15: exit codes

def test_exit_high_fail(wiki: Path, capsys):
    _write(wiki / "wiki/concepts/lonely.md", _page("lonely"))
    rc = main([str(wiki), "--fail-on=high"])
    assert rc == EXIT_FAIL
    capsys.readouterr()


def test_exit_only_low(wiki: Path, capsys):
    # source page (orphan-exempt), in index, only triggers stale_candidate.
    _write(
        wiki / "wiki/sources/old.md",
        _page("old", kind="raw_source", meta_extra="updated: 2020-01-01\n"),
    )
    idx_path = wiki / "index.md"
    idx_path.write_text(
        idx_path.read_text(encoding="utf-8")
        + "\n- [old](wiki/sources/old.md)\n",
        encoding="utf-8",
    )
    rc = main([str(wiki), "--fail-on=high"])
    err = capsys.readouterr().err
    assert rc == EXIT_OK, err
    # Same wiki with --fail-on=low should fail.
    rc2 = main([str(wiki), "--fail-on=low"])
    capsys.readouterr()
    assert rc2 == EXIT_FAIL


def test_exit_schema_missing_wiki(tmp_path: Path, capsys):
    rc = main([str(tmp_path)])
    assert rc == EXIT_SCHEMA
    err = capsys.readouterr().err
    assert "[ERR_SCHEMA]" in err


def test_exit_security_symlink(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    init("D", "d", str(tmp_path / "real"))
    sym = tmp_path / "sym"
    sym.symlink_to(tmp_path / "real", target_is_directory=True)
    rc = main([str(sym)])
    assert rc == EXIT_SECURITY
    err = capsys.readouterr().err
    assert "[ERR_SECURITY]" in err


# Crit 16 (no-network) is enforced for the entire suite by the autouse
# ``no_network`` fixture above.

"""Graph lint (M4).

Pure-stdlib graph-aware linter for an LLM-Wiki produced by M1+M2+M3.
Implements the eight rules and five discourse states defined in MASTER
Appendix C. Strictly read-only against the wiki it analyzes; only
``--log`` appends a single W5 line to ``log.md``.

Public surface (consumed by M6 cron):
    lint_wiki(wiki_root: Path) -> LintReport
    report_text(report: LintReport) -> str
    report_json(report: LintReport) -> str
    main()                                # CLI

Exit codes:
    0  no issues at-or-above --fail-on threshold
    1  issues at-or-above --fail-on threshold
    2  [ERR_SCHEMA] (wiki_root malformed)
    4  [ERR_SECURITY] (path escape, symlink leaving wiki_root)
    5  [ERR_RUNTIME]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

__all__ = [
    "LintReport", "Issue",
    "lint_wiki", "report_text", "report_json", "main",
    "RELATION_CODES", "GENERIC_RELATION_CODE",
    "RELATEDTO_THRESHOLD", "RELATION_MIN_SAMPLE",
    "HUB_AND_SPOKE_THRESHOLD", "STALE_DAYS", "BIASED_INBOUND_SHARE",
    "EXIT_OK", "EXIT_FAIL", "EXIT_SCHEMA", "EXIT_SECURITY", "EXIT_RUNTIME",
    "LOG_LINE_RE",
    "LintError", "SchemaError", "SecurityError",
]

# ---- constants -------------------------------------------------------------

# Bounded relation-code vocabulary (mirrors templates/SCHEMA.md "Relation
# Codes"). Hardcoded by design: SCHEMA.md is a human template, not a
# machine-parseable spec. If the vocabulary changes there, this constant
# MUST be updated in lockstep.
RELATION_CODES: frozenset[str] = frozenset({
    "isA", "partOf", "hasAttribute", "relatedTo", "dependentOn",
    "causes", "locatedIn", "occursAt", "derivedFrom", "opposes",
})
GENERIC_RELATION_CODE = "relatedTo"
RELATEDTO_THRESHOLD = 0.70
RELATION_MIN_SAMPLE = 10
HUB_AND_SPOKE_THRESHOLD = 0.40
STALE_DAYS = 30
BIASED_INBOUND_SHARE = 0.50

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SCHEMA = 2
EXIT_SECURITY = 4
EXIT_RUNTIME = 5

_SEV_RANK = {"high": 3, "medium": 2, "low": 1}
_FAIL_THRESHOLD = {"high": 3, "medium": 2, "low": 1, "none": 99}

LOG_LINE_RE = re.compile(
    r"^## \[\d{4}-\d{2}-\d{2}\] lint \| \d+ issues \| "
    r"state=(EMPTY|BIASED|FOCUSED|DIVERSIFIED|DISPERSED)$"
)

# ---- regex parsers ---------------------------------------------------------

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+\.md)(?:#[^)]*)?\)")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CROSSREF_HEADER_RE = re.compile(
    r"^\s{0,3}#{2,3}\s*Cross[- ]References?\b", re.IGNORECASE
)
_ANY_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_CROSSREF_ITEM_RE = re.compile(
    r"""^\s*[-*+]\s+
        \[[^\]]+\]\(([^)\s]+)\)
        \s*[\u2014\u2013\-]{1,2}\s*
        (?:\*\*)?
        ([A-Za-z][A-Za-z0-9_]*)
        (?:\*\*)?
        \s*:""",
    re.VERBOSE,
)


# ---- types -----------------------------------------------------------------

class Issue(TypedDict):
    severity: Literal["high", "medium", "low"]
    rule: str
    message: str
    page: NotRequired[str]
    target: NotRequired[str]


@dataclass(frozen=True)
class LintReport:
    wiki_root: Path
    pages: int
    edges: int
    components: int
    largest_component: int
    discourse_state: Literal[
        "EMPTY", "BIASED", "FOCUSED", "DIVERSIFIED", "DISPERSED"
    ]
    issues: list[Issue]


class LintError(Exception):
    exit_code = EXIT_RUNTIME
    tag = "[ERR_RUNTIME]"


class SchemaError(LintError):
    exit_code = EXIT_SCHEMA
    tag = "[ERR_SCHEMA]"


class SecurityError(LintError):
    exit_code = EXIT_SECURITY
    tag = "[ERR_SECURITY]"


# ---- helpers ---------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def _extract_relation_codes(body: str) -> list[str]:
    codes: list[str] = []
    in_section = False
    for line in body.splitlines():
        if _CROSSREF_HEADER_RE.match(line):
            in_section = True
            continue
        if in_section and _ANY_HEADER_RE.match(line):
            in_section = False
            continue
        if in_section:
            m = _CROSSREF_ITEM_RE.match(line)
            if m:
                codes.append(m.group(2))
    return codes


def _ensure_under(root_resolved: Path, candidate: Path) -> None:
    """Raise ``SecurityError`` if ``candidate`` resolves outside ``root_resolved``."""
    try:
        candidate.resolve().relative_to(root_resolved)
    except ValueError as e:
        raise SecurityError(f"path escapes wiki root: {candidate}") from e


# ---- scan + graph ----------------------------------------------------------

def _scan(wiki_root: Path) -> dict[str, dict]:
    """Walk ``wiki/`` and return ``{posix_rel: {meta, links_out, body, abs}}``.

    ``links_out`` is a list of ``(raw_target, link_rel)`` where ``link_rel`` is
    the page path relative to ``wiki_root`` if resolvable inside it, or ``""``
    if the link points outside ``wiki_root``.
    """
    wiki_dir = wiki_root / "wiki"
    pages: dict[str, dict] = {}
    if not wiki_dir.is_dir():
        return pages
    root_resolved = wiki_root.resolve()
    for dirpath, _dirnames, filenames in os.walk(wiki_dir, followlinks=False):
        dpath = Path(dirpath)
        _ensure_under(root_resolved, dpath)
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            full = dpath / name
            if full.is_symlink():
                _ensure_under(root_resolved, full)
            try:
                text = full.read_text(encoding="utf-8")
            except OSError:
                continue
            rel = full.relative_to(wiki_root).as_posix()
            meta = _parse_frontmatter(text)
            links_out: list[tuple[str, str]] = []
            for _label, target in _LINK_RE.findall(text):
                resolved = (full.parent / target).resolve()
                try:
                    link_rel = resolved.relative_to(root_resolved).as_posix()
                except ValueError:
                    link_rel = ""
                links_out.append((target, link_rel))
            pages[rel] = {
                "meta": meta,
                "links_out": links_out,
                "body": text,
                "abs": full,
            }
    return pages


def _build_graph(
    pages: dict[str, dict],
) -> tuple[list[str], list[tuple[str, str]], Counter, list[tuple[str, str]]]:
    nodes = sorted(pages.keys())
    nodeset = set(nodes)
    edges: list[tuple[str, str]] = []
    broken: list[tuple[str, str]] = []
    inbound: Counter = Counter()
    for rel in nodes:
        for _raw_target, link_rel in pages[rel]["links_out"]:
            if not link_rel or not link_rel.startswith("wiki/"):
                # External link, raw/, or unresolvable — not a wiki edge.
                continue
            if not link_rel.endswith(".md"):
                continue
            if link_rel in nodeset:
                edges.append((rel, link_rel))
                inbound[link_rel] += 1
            else:
                broken.append((rel, link_rel))
    return nodes, edges, inbound, broken


def _components(
    nodes: list[str], edges: list[tuple[str, str]]
) -> list[set[str]]:
    adj: dict[str, set[str]] = defaultdict(set)
    for s, d in edges:
        adj[s].add(d)
        adj[d].add(s)
    seen: set[str] = set()
    comps: list[set[str]] = []
    for n in nodes:
        if n in seen:
            continue
        stack = [n]
        comp: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.add(cur)
            stack.extend(adj.get(cur, set()) - seen)
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def _classify(
    nodes: list[str],
    edges: list[tuple[str, str]],
    inbound: Counter,
    comps: list[set[str]],
) -> str:
    n = len(nodes)
    if n == 0:
        return "EMPTY"
    if inbound and edges:
        max_share = max(inbound.values()) / len(edges)
        if max_share > BIASED_INBOUND_SHARE:
            return "BIASED"
    if not edges:
        return "DISPERSED" if n > 1 else "FOCUSED"
    largest = len(comps[0])
    largest_ratio = largest / n
    edges_per_node = len(edges) / n
    if largest_ratio > 0.85 and edges_per_node < 1.5:
        return "FOCUSED"
    if len(comps) > n / 3:
        return "DISPERSED"
    return "DIVERSIFIED"


# ---- rules -----------------------------------------------------------------

def _today() -> date:
    return date.today()


def _lint_rules(
    pages: dict[str, dict],
    nodes: list[str],
    edges: list[tuple[str, str]],
    inbound: Counter,
    broken: list[tuple[str, str]],
    index_text: str,
) -> list[Issue]:
    issues: list[Issue] = []

    # 1. orphan (HIGH) — wiki page with 0 inbound links; sources exempt.
    for rel in nodes:
        if inbound.get(rel, 0) == 0 and "/sources/" not in rel:
            issues.append({
                "severity": "high",
                "rule": "orphan",
                "message": f"Wiki page has zero inbound links: {rel}",
                "page": rel,
            })

    # 2. broken_link (HIGH).
    for src, tgt in broken:
        issues.append({
            "severity": "high",
            "rule": "broken_link",
            "message": f"{src} → {tgt} (target not found)",
            "page": src,
            "target": tgt,
        })

    # 3. index_gap (MEDIUM) — page not mentioned in index.md.
    for rel in nodes:
        basename = os.path.basename(rel)
        if basename in index_text or rel in index_text:
            continue
        issues.append({
            "severity": "medium",
            "rule": "index_gap",
            "message": f"Page not listed in index.md: {rel}",
            "page": rel,
        })

    # 4. hub_and_spoke (MEDIUM) — single page absorbs >40% of inbound edges.
    total_in = sum(inbound.values())
    if total_in > 0:
        for rel, count in inbound.most_common(3):
            ratio = count / total_in
            if ratio > HUB_AND_SPOKE_THRESHOLD:
                issues.append({
                    "severity": "medium",
                    "rule": "hub_and_spoke",
                    "message": (
                        f"{rel} absorbs {ratio:.0%} of all wiki "
                        f"cross-references — likely centralized framing"
                    ),
                    "page": rel,
                })

    # 5/6. relation code rules.
    relation_counter: Counter = Counter()
    unknown_by_page: dict[str, list[str]] = defaultdict(list)
    for rel in nodes:
        for code in _extract_relation_codes(pages[rel]["body"]):
            if code in RELATION_CODES:
                relation_counter[code] += 1
            else:
                unknown_by_page[rel].append(code)
    for rel in sorted(unknown_by_page.keys()):
        unique = sorted(set(unknown_by_page[rel]))
        sample = ", ".join(unique[:5]) + ("…" if len(unique) > 5 else "")
        issues.append({
            "severity": "low",
            "rule": "unknown_relation_code",
            "message": (
                f"{rel} uses relation code(s) outside SCHEMA "
                f"vocabulary: {sample}"
            ),
            "page": rel,
        })
    total_relations = sum(relation_counter.values())
    if total_relations >= RELATION_MIN_SAMPLE:
        share = (
            relation_counter.get(GENERIC_RELATION_CODE, 0) / total_relations
        )
        if share > RELATEDTO_THRESHOLD:
            issues.append({
                "severity": "medium",
                "rule": "relation_code_distribution",
                "message": (
                    f"{GENERIC_RELATION_CODE} accounts for {share:.0%} of "
                    f"{total_relations} cross-references (threshold "
                    f"{RELATEDTO_THRESHOLD:.0%}); relational structure is "
                    f"under-specified"
                ),
            })

    # 7. asymmetric_coverage (LOW).
    by_type: Counter = Counter()
    for rel in nodes:
        meta = pages[rel]["meta"]
        t = meta.get("entity_type") or meta.get("type") or "unknown"
        by_type[t] += 1
    if len(by_type) >= 2:
        sizes = sorted(by_type.values(), reverse=True)
        if sizes[0] >= 5 and sizes[-1] <= max(1, sizes[0] // 5):
            issues.append({
                "severity": "low",
                "rule": "asymmetric_coverage",
                "message": (
                    f"Page-type distribution is uneven: {dict(by_type)}"
                ),
            })

    # 8. stale_candidate (LOW).
    today = _today()
    cutoff = today - timedelta(days=STALE_DAYS)
    for rel in nodes:
        meta = pages[rel]["meta"]
        ts = meta.get("updated") or meta.get("ingested")
        if not ts:
            continue
        try:
            d = datetime.strptime(ts, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            age = (today - d).days
            issues.append({
                "severity": "low",
                "rule": "stale_candidate",
                "message": f"{rel} not updated in {age} days",
                "page": rel,
            })

    # Deterministic order: severity desc, then rule, then page, then message.
    issues.sort(key=lambda i: (
        -_SEV_RANK[i["severity"]],
        i["rule"],
        i.get("page", ""),
        i["message"],
    ))
    return issues


# ---- public entry point ----------------------------------------------------

def lint_wiki(wiki_root: Path) -> LintReport:
    wiki_root = Path(wiki_root)
    if wiki_root.is_symlink():
        raise SecurityError(f"wiki root is a symlink: {wiki_root}")
    if not wiki_root.is_dir():
        raise SchemaError(f"wiki root not a directory: {wiki_root}")
    if not (wiki_root / "wiki").is_dir():
        raise SchemaError(f"missing wiki/ under {wiki_root}")
    if not (wiki_root / "SCHEMA.md").is_file():
        raise SchemaError(f"missing SCHEMA.md under {wiki_root}")
    if not (wiki_root / "index.md").is_file():
        raise SchemaError(f"missing index.md under {wiki_root}")

    pages = _scan(wiki_root)
    nodes, edges, inbound, broken = _build_graph(pages)
    comps = _components(nodes, edges)
    state = _classify(nodes, edges, inbound, comps)
    index_text = (wiki_root / "index.md").read_text(encoding="utf-8")
    issues = _lint_rules(pages, nodes, edges, inbound, broken, index_text)
    return LintReport(
        wiki_root=wiki_root,
        pages=len(nodes),
        edges=len(edges),
        components=len(comps),
        largest_component=len(comps[0]) if comps else 0,
        discourse_state=state,  # type: ignore[arg-type]
        issues=issues,
    )


# ---- reporting -------------------------------------------------------------

def report_text(r: LintReport) -> str:
    lines = [
        "LINT REPORT",
        "=" * 60,
        f"Wiki root:       {r.wiki_root}",
        f"Pages:           {r.pages}",
        f"Edges:           {r.edges}",
        f"Components:      {r.components}",
        f"Largest comp:    {r.largest_component}",
        f"Discourse state: {r.discourse_state}",
        f"Issues:          {len(r.issues)}",
        "",
    ]
    for sev in ("high", "medium", "low"):
        sub = [i for i in r.issues if i["severity"] == sev]
        if not sub:
            continue
        lines.append(f"[{sev.upper()}] {len(sub)}")
        for i in sub[:25]:
            lines.append(f"  - {i['rule']}: {i['message']}")
        if len(sub) > 25:
            lines.append(f"  … and {len(sub) - 25} more")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def report_json(r: LintReport) -> str:
    return json.dumps({
        "wiki_root": str(r.wiki_root),
        "pages": r.pages,
        "edges": r.edges,
        "components": r.components,
        "largest_component": r.largest_component,
        "discourse_state": r.discourse_state,
        "issues": [dict(i) for i in r.issues],
    }, indent=2, sort_keys=True) + "\n"


def _append_log(wiki_root: Path, r: LintReport) -> None:
    log_path = wiki_root / "log.md"
    line = (
        f"## [{_today().isoformat()}] lint | "
        f"{len(r.issues)} issues | state={r.discourse_state}\n"
    )
    existing = (
        log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    )
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(sep + line)


# ---- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wiki.graph_lint")
    ap.add_argument("wiki_root")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--log", action="store_true")
    ap.add_argument(
        "--fail-on",
        choices=["high", "medium", "low", "none"],
        default="high",
    )
    args = ap.parse_args(argv)

    try:
        r = lint_wiki(Path(args.wiki_root))
    except LintError as e:
        sys.stderr.write(f"{e.tag} {e}\n")
        return e.exit_code
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"[ERR_RUNTIME] {e}\n")
        return EXIT_RUNTIME

    sys.stdout.write(report_json(r) if args.json else report_text(r))

    if args.log:
        try:
            _append_log(Path(args.wiki_root), r)
        except OSError as e:  # pragma: no cover
            sys.stderr.write(f"[ERR_RUNTIME] log append failed: {e}\n")
            return EXIT_RUNTIME

    threshold = _FAIL_THRESHOLD[args.fail_on]
    triggered = any(_SEV_RANK[i["severity"]] >= threshold for i in r.issues)
    return EXIT_FAIL if triggered else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

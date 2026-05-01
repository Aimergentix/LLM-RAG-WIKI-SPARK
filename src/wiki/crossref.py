"""DAG walker for cross-ref ordering + concept/entity merge primitives.

Per M3 contract criteria 5–8.

Topological sort is **deterministic**: at each step we emit the
alphabetically-smallest slug among the currently-eligible (zero-indegree)
nodes. Cycles raise ``CycleError``.
"""

from __future__ import annotations

import heapq
import datetime as _dt
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from . import _frontmatter as fm
from .agent_seam import Contradiction, TouchedPage
from .init import substitute


class CycleError(Exception):
    """Raised when ``plan_crossrefs`` returns a dependency cycle."""


def topo_order(pages: list[TouchedPage]) -> list[TouchedPage]:
    """Deterministic topological order using Kahn's algorithm: depends-on first, alphabetical tiebreak."""
    by_slug = {p["slug"]: p for p in pages}
    indeg: dict[str, int] = {s: 0 for s in by_slug}
    edges: dict[str, set[str]] = defaultdict(set)  # dep -> dependents
    for p in pages:
        for dep in p.get("depends_on", []):
            if dep not in by_slug:
                # External dep; ignore (the page may already exist on disk).
                continue
            if p["slug"] in edges[dep]:
                continue
            edges[dep].add(p["slug"])
            indeg[p["slug"]] += 1

    # Use a heap for O(log N) alphabetical tie-breaking
    ready = [s for s, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    
    out: list[TouchedPage] = []
    while ready:
        s = heapq.heappop(ready)
        out.append(by_slug[s])
        for dependent in edges[s]:
            indeg[dependent] -= 1
            if indeg[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(out) != len(by_slug):
        raise CycleError(f"cycle detected among slugs: {sorted(by_slug)}")
    return out


def render_new_page(
    *,
    kind: str,
    title: str,
    slug: str,
    date: str,
    entity_type: str,
    template_text: str,
) -> str:
    """Hydrate a fresh concept/entity page from its template."""
    mapping = {
        "DOMAIN": "",
        "DESCRIPTION": "",
        "DATE": date,
        "NAME": title,
        "TITLE": title,
        "SLUG": slug,
        "CONVERTER": "",
        "QUESTION": "",
        "ENTITY_TYPE": entity_type,
    }
    return substitute(template_text, mapping)


def merge_page(
    *,
    existing: str,
    merge_md: str,
    contradictions: list[Contradiction],
    source_slug: str,
    is_entity: bool,
) -> str:
    """Append ``merge_md`` (and contradiction lines) under ``## Cross-References``.

    Lines already present in the page are not duplicated. For entities,
    bumps ``source_count`` by 1.
    """
    fm_data, fm_keys, body = fm.split(existing)

    # Bump source_count once.
    if is_entity and "source_count" in fm_data:
        try:
            fm_data["source_count"] = str(int(str(fm_data["source_count"])) + 1)
        except ValueError:
            pass

    # Build the lines to append.
    new_lines: list[str] = []
    for c in contradictions:
        new_lines.append(_contradiction_line(source_slug, c))
    for line in merge_md.splitlines():
        if line.strip():
            new_lines.append(line.rstrip())

    body = _append_to_section(body, "## Cross-References", new_lines)

    return fm.render(fm_data, fm_keys, body)


def _append_to_section(body: str, heading: str, lines: list[str]) -> str:
    """Append ``lines`` under ``heading`` (creating the section if absent).

    Skips lines whose stripped form is already present anywhere in the
    target section to keep the merge idempotent.
    """
    if not lines:
        return body

    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
    m = pattern.search(body)
    if m is None:
        # Append a fresh section at the end.
        prefix = body if body.endswith("\n") else body + "\n"
        block = f"\n{heading}\n\n" + "\n".join(lines) + "\n"
        return prefix + block

    sec_start = m.end()
    next_h2 = re.compile(r"^## +", re.MULTILINE).search(body, sec_start + 1)
    sec_end = next_h2.start() if next_h2 else len(body)
    section = body[sec_start:sec_end]

    existing_lines = {l.strip() for l in section.splitlines() if l.strip()}
    fresh = [l for l in lines if l.strip() not in existing_lines]
    if not fresh:
        return body

    section = section.rstrip("\n") + "\n" + "\n".join(fresh) + "\n"
    if next_h2 is not None:
        section += "\n"
    return body[:sec_start] + section + body[sec_end:]


def _contradiction_line(source_slug: str, c: Contradiction) -> str:
    other = c["with_source_slug"]
    return (
        f"> ⚠️ Contradiction: [{source_slug}](../sources/{source_slug}.md) "
        f"says {c['claim']}; "
        f"[{other}](../sources/{other}.md) says {c['counter_claim']}"
    )


def today_iso() -> str:
    return _dt.date.today().isoformat()


def collect_existing_pages(wiki_root: Path, slugs: Iterable[str]) -> dict[str, str]:
    """Return ``{slug: page_text}`` for any of ``slugs`` that already exist.

    Looks under both ``wiki/concepts/`` and ``wiki/entities/``.
    """
    out: dict[str, str] = {}
    for slug in slugs:
        for kind in ("concepts", "entities"):
            p = wiki_root / "wiki" / kind / f"{slug}.md"
            if p.is_file():
                out[slug] = p.read_text(encoding="utf-8")
                break
    return out

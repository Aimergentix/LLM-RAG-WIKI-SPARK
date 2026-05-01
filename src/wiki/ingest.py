"""M3 ingest orchestrator + CLI.

Single-source ingest: ``raw/{slug}.md`` -> ``wiki/sources/{slug}.md`` plus
DAG-ordered concept/entity merges, glossary patch, index/log updates. All
on-disk mutations are 2-phase atomic (write *.tmp, then os.replace each).

Per START-PROMPT §5 M3 contract; MASTER §6 W3 + §7 + §8 + §9.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

from . import _frontmatter as fm
from . import crossref as crossref_mod
from . import glossary as glossary_mod
from .agent_seam import DeterministicStubAgent, IngestAgent, TouchedPage
from .crossref import CycleError
from .init import substitute

ERR_SCHEMA = "[ERR_SCHEMA]"
ERR_SECURITY = "[ERR_SECURITY]"
ERR_RUNTIME = "[ERR_RUNTIME]"

EXIT_OK = 0
EXIT_SCHEMA = 2
EXIT_EXISTS = 3
EXIT_SECURITY = 4
EXIT_RUNTIME = 5

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_NEEDS_VISION_RE = re.compile(r"<!--\s*needs-vision:\s*([^>]*?)\s*-->")
_LOG_DATE = re.compile(r"^## \[\d{4}-\d{2}-\d{2}\]")

_KIND_DIR = {"concept": "concepts", "entity": "entities"}


class IngestError(Exception):
    def __init__(self, code: str, msg: str, exit_code: int = EXIT_RUNTIME) -> None:
        super().__init__(f"{code}: {msg}")
        self.code = code
        self.exit_code = exit_code


class IngestReport(NamedTuple):
    source_path: Path
    touched_pages: list[Path]
    glossary_added: list[str]


# ---------------------------------------------------------------- helpers

def _find_wiki_root(start: Path) -> Path:
    cur = start.resolve()
    for d in [cur, *cur.parents]:
        if (
            (d / "SCHEMA.md").is_file()
            and (d / ".wiki" / ".converted.json").is_file()
            and (d / "entry").is_dir()
            and (d / "raw").is_dir()
        ):
            return d
    raise IngestError(ERR_SCHEMA, f"no wiki root found from {start}", EXIT_SCHEMA)


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise IngestError(
            ERR_SECURITY, f"invalid slug: {slug!r}", EXIT_SECURITY
        )


def _resolve_raw(wiki_root: Path, arg: str) -> str:
    """Resolve user arg to a slug and validate the raw path is safe."""
    raw_dir = (wiki_root / "raw").resolve()

    if "/" in arg or arg.endswith(".md"):
        p = Path(arg)
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
        try:
            rel = p.relative_to(raw_dir)
        except ValueError:
            raise IngestError(
                ERR_SECURITY,
                f"path not inside {raw_dir}: {p}",
                EXIT_SECURITY,
            )
        if rel.parent != Path("."):
            raise IngestError(
                ERR_SECURITY, f"nested raw paths unsupported: {rel}", EXIT_SECURITY
            )
        slug = rel.name[: -len(".md")] if rel.name.endswith(".md") else rel.name
    else:
        slug = arg
    _validate_slug(slug)

    raw_path = raw_dir / f"{slug}.md"
    if raw_path.is_symlink():
        raise IngestError(
            ERR_SECURITY, f"symlinks not followed: {raw_path}", EXIT_SECURITY
        )
    if not raw_path.is_file():
        raise IngestError(
            ERR_SCHEMA, f"raw page not found: raw/{slug}.md", EXIT_SCHEMA
        )
    return slug


def _load_manifest(wiki_root: Path) -> dict:
    p = wiki_root / ".wiki" / ".converted.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise IngestError(ERR_SCHEMA, f"manifest unreadable: {exc}", EXIT_SCHEMA)
    if not isinstance(data, dict):
        raise IngestError(ERR_SCHEMA, "manifest is not an object", EXIT_SCHEMA)
    return data


def _find_manifest_entry(manifest: dict, slug: str) -> dict:
    for key, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("slug") == slug:
            return entry
    raise IngestError(
        ERR_SCHEMA, f"slug not in manifest: {slug}", EXIT_SCHEMA
    )


def _derive_title(raw_md: str, slug: str) -> str:
    for line in raw_md.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or slug
    # Skip frontmatter block for the H1 search.
    if raw_md.startswith("---"):
        end = raw_md.find("\n---", 3)
        if end != -1:
            return _derive_title(raw_md[end + 4 :], slug)
    return slug.replace("-", " ").replace("_", " ").title()


def _render_source_page(
    *,
    template_text: str,
    title: str,
    slug: str,
    date: str,
    converter: str,
    takeaways: list[str],
) -> str:
    mapping = {
        "DOMAIN": "",
        "DESCRIPTION": "",
        "DATE": date,
        "NAME": title,
        "TITLE": title,
        "SLUG": slug,
        "CONVERTER": converter or "copy",
        "QUESTION": "",
        "ENTITY_TYPE": "person",
    }
    rendered = substitute(template_text, mapping)
    # Replace the empty Key Points block with the takeaways.
    if takeaways:
        block = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(takeaways))
        rendered = re.sub(
            r"(## Key Points\n)1\.\n2\.\n3\.\n",
            lambda m: m.group(1) + block + "\n",
            rendered,
            count=1,
        )
    return rendered


# ------------------------------------------------------------ index update

_INDEX_SECTION = {
    "source": "## Sources",
    "concept": "## Concepts",
    "entity": "## Entities",
}
_INDEX_LINK = {
    "source": "wiki/sources",
    "concept": "wiki/concepts",
    "entity": "wiki/entities",
}


def _update_index(index_md: str, items: list[tuple[str, str, str]]) -> str:
    """``items`` = list of ``(kind, title, slug)``. Returns new index text."""
    text = index_md
    grouped: dict[str, list[tuple[str, str]]] = {}
    for kind, title, slug in items:
        grouped.setdefault(kind, []).append((title, slug))
    for kind, entries in grouped.items():
        heading = _INDEX_SECTION[kind]
        prefix = _INDEX_LINK[kind]
        new_lines = [
            f"- [{title}]({prefix}/{slug}.md)" for title, slug in entries
        ]
        text = _insert_into_index(text, heading, prefix, new_lines)
    return text


def _insert_into_index(
    text: str, heading: str, link_prefix: str, new_lines: list[str]
) -> str:
    h_re = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
    m = h_re.search(text)
    if m is None:
        appended = "\n" + heading + "\n\n" + "\n".join(sorted(new_lines)) + "\n"
        if not text.endswith("\n"):
            text += "\n"
        return text + appended
    sec_start = m.end()
    next_h2 = re.compile(r"^## +", re.MULTILINE).search(text, sec_start + 1)
    sec_end = next_h2.start() if next_h2 else len(text)
    section = text[sec_start:sec_end]

    # Existing link lines under this section.
    link_re = re.compile(rf"^- \[.+?\]\({re.escape(link_prefix)}/[^)]+\)$")
    existing_lines = []
    other_lines = []
    for line in section.splitlines():
        if link_re.match(line.strip()):
            existing_lines.append(line.strip())
        else:
            other_lines.append(line)

    target_paths = {_link_target(l) for l in existing_lines}
    for nl in new_lines:
        if _link_target(nl) not in target_paths:
            existing_lines.append(nl)
            target_paths.add(_link_target(nl))
    existing_lines.sort(key=_link_target)

    # Reassemble: preserve preface (other_lines until the first link, or all
    # if no links existed), then the sorted link block.
    preface_end = len(other_lines)
    rebuilt = "\n".join(other_lines).rstrip("\n")
    rebuilt = (rebuilt + "\n\n" if rebuilt else "\n") + "\n".join(existing_lines) + "\n"
    if next_h2 is not None:
        rebuilt += "\n"
    return text[:sec_start] + "\n" + rebuilt + text[sec_end:]


def _link_target(line: str) -> str:
    m = re.search(r"\(([^)]+)\)", line)
    return m.group(1) if m else line


# ---------------------------------------------------------- atomic writer

def _atomic_write_all(plan: dict[Path, str]) -> None:
    """Write ``{path: content}`` atomically. Two-phase: temps, then replaces.

    If any ``os.replace`` raises, abort and clean up remaining temps. The
    already-replaced files keep their new content (best-effort), but the
    test injects a stub that always raises so no replace ever lands.
    """
    temps: list[tuple[Path, Path]] = []
    try:
        for target, content in plan.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            temps.append((tmp, target))
        for tmp, target in temps:
            os.replace(tmp, target)
    finally:
        for tmp, _ in temps:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


# ------------------------------------------------------------- ingest_one

def ingest_one(
    wiki_root: Path,
    slug: str,
    agent: IngestAgent,
    *,
    force: bool = False,
    today: str | None = None,
) -> IngestReport:
    wiki_root = wiki_root.resolve()
    _validate_slug(slug)

    raw_path = wiki_root / "raw" / f"{slug}.md"
    if raw_path.is_symlink() or not raw_path.is_file():
        raise IngestError(
            ERR_SCHEMA, f"raw page not found: raw/{slug}.md", EXIT_SCHEMA
        )

    manifest = _load_manifest(wiki_root)
    entry = _find_manifest_entry(manifest, slug)
    status = entry.get("status", "ok")
    if status not in {"ok", "needs_vision"}:
        raise IngestError(
            ERR_SCHEMA,
            f"manifest status not ingestable: {status}",
            EXIT_SCHEMA,
        )

    source_target = wiki_root / "wiki" / "sources" / f"{slug}.md"
    if source_target.exists() and not force:
        raise IngestError(
            ERR_RUNTIME,
            f"source page already exists: wiki/sources/{slug}.md (use --force)",
            EXIT_EXISTS,
        )

    raw_md = raw_path.read_text(encoding="utf-8")
    schema_path = wiki_root / "SCHEMA.md"
    index_path = wiki_root / "index.md"
    log_path = wiki_root / "log.md"
    schema_md = schema_path.read_text(encoding="utf-8")
    index_md = index_path.read_text(encoding="utf-8")
    log_md = log_path.read_text(encoding="utf-8")

    # Vision marker resolution (does NOT touch raw/ on disk).
    vm = _NEEDS_VISION_RE.search(raw_md)
    if vm or status == "needs_vision":
        marker_arg = Path(vm.group(1).strip()) if vm else raw_path
        asset = None
        if vm:
            cand = (wiki_root / "raw" / "assets" / Path(vm.group(1).strip()).name)
            if cand.is_file():
                asset = cand
        vision_text = agent.resolve_vision(marker_path=marker_arg, asset_path=asset)
        raw_md_for_agent = vision_text + "\n\n" + raw_md
    else:
        raw_md_for_agent = raw_md

    takeaways = agent.extract_takeaways(
        raw_md=raw_md_for_agent, schema_md=schema_md, index_md=index_md
    )
    if not 1 <= len(takeaways) <= 6:
        raise IngestError(
            ERR_RUNTIME,
            f"agent returned {len(takeaways)} takeaways (need 1-6)",
            EXIT_RUNTIME,
        )

    title = _derive_title(raw_md, slug)
    date = today or crossref_mod.today_iso()

    # ----- source page render
    src_template_text = _read_template(wiki_root, "source.md")
    source_text = _render_source_page(
        template_text=src_template_text,
        title=title,
        slug=slug,
        date=date,
        converter=str(entry.get("converter", "copy")),
        takeaways=takeaways,
    )

    # ----- cross-ref plan
    plan = agent.plan_crossrefs(
        raw_md=raw_md_for_agent,
        takeaways=takeaways,
        existing_pages=crossref_mod.collect_existing_pages(
            wiki_root, [p["slug"] for p in []]
        ),
    )
    # Validate each TouchedPage minimally.
    for p in plan:
        if p.get("kind") not in {"concept", "entity"}:
            raise IngestError(ERR_SCHEMA, f"bad TouchedPage kind: {p}", EXIT_SCHEMA)
        _validate_slug(p["slug"])

    try:
        ordered = crossref_mod.topo_order(plan)
    except CycleError as exc:
        raise IngestError(ERR_SCHEMA, str(exc), EXIT_SCHEMA)

    write_plan: dict[Path, str] = {source_target: source_text}
    touched_index_items: list[tuple[str, str, str]] = [("source", title, slug)]

    bumped_entities: set[str] = set()
    for tp in ordered:
        kind = tp["kind"]
        page_path = wiki_root / "wiki" / _KIND_DIR[kind] / f"{tp['slug']}.md"
        if page_path.exists():
            existing = page_path.read_text(encoding="utf-8")
            contradictions = agent.find_contradictions(
                page_slug=tp["slug"],
                page_md=existing,
                new_fragment=tp.get("merge_md", ""),
            )
            new_text = crossref_mod.merge_page(
                existing=existing,
                merge_md=tp.get("merge_md", ""),
                contradictions=contradictions,
                source_slug=slug,
                is_entity=(kind == "entity" and tp["slug"] not in bumped_entities),
            )
            if kind == "entity":
                bumped_entities.add(tp["slug"])
        else:
            template_text = _read_template(wiki_root, f"{kind}.md")
            new_text = crossref_mod.render_new_page(
                kind=kind,
                title=tp["title"],
                slug=tp["slug"],
                date=date,
                entity_type=tp.get("entity_type", "person"),
                template_text=template_text,
            )
            contradictions = agent.find_contradictions(
                page_slug=tp["slug"],
                page_md=new_text,
                new_fragment=tp.get("merge_md", ""),
            )
            new_text = crossref_mod.merge_page(
                existing=new_text,
                merge_md=tp.get("merge_md", ""),
                contradictions=contradictions,
                source_slug=slug,
                is_entity=False,  # don't bump fresh page (it starts at 1)
            )
            if kind == "entity":
                bumped_entities.add(tp["slug"])
        write_plan[page_path] = new_text
        touched_index_items.append((kind, tp["title"], tp["slug"]))

    # ----- glossary
    existing_terms = glossary_mod.existing_terms(schema_md)
    new_terms = agent.detect_glossary_terms(
        raw_md=raw_md_for_agent,
        takeaways=takeaways,
        existing_terms=existing_terms,
    )
    new_schema = glossary_mod.patch(schema_md, new_terms)
    glossary_added = [t for t, _ in new_terms if t not in existing_terms]
    if new_schema != schema_md:
        write_plan[schema_path] = new_schema

    # ----- index
    new_index = _update_index(index_md, touched_index_items)
    if new_index != index_md:
        write_plan[index_path] = new_index

    # ----- log
    n_touched = 1 + sum(1 for tp in ordered)
    log_line = (
        f"## [{date}] ingest | {title} | sources/{slug}.md "
        f"| {n_touched} pages touched\n"
    )
    new_log = log_md if log_md.endswith("\n") else log_md + "\n"
    new_log += log_line
    write_plan[log_path] = new_log

    # ----- safety: every target must be inside wiki_root and outside read-only dirs
    for target in write_plan:
        try:
            rel = target.resolve().relative_to(wiki_root)
        except ValueError:
            raise IngestError(
                ERR_SECURITY, f"write outside wiki root: {target}", EXIT_SECURITY
            )
        first = rel.parts[0] if rel.parts else ""
        if first in {"raw", "entry", ".wiki"}:
            raise IngestError(
                ERR_SECURITY, f"write under read-only dir: {target}", EXIT_SECURITY
            )

    _atomic_write_all(write_plan)

    return IngestReport(
        source_path=source_target,
        touched_pages=[
            wiki_root / "wiki" / _KIND_DIR[tp["kind"]] / f"{tp['slug']}.md"
            for tp in ordered
        ],
        glossary_added=glossary_added,
    )


def _read_template(wiki_root: Path, name: str) -> str:
    """Read a page template. Looks for a repo-root templates/ first, then
    falls back to ``$WIKI_ROOT/.wiki/templates/`` if a wiki-local copy
    has been installed."""
    # Repo root: src/wiki/ingest.py -> repo_root = parents[2]
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "templates" / "pages" / name,
        wiki_root / ".wiki" / "templates" / "pages" / name,
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8")
    raise IngestError(ERR_SCHEMA, f"template missing: pages/{name}", EXIT_SCHEMA)


# --------------------------------------------------------------------- CLI

def _load_agent(spec: str | None) -> IngestAgent:
    if spec is None:
        if os.environ.get("LLMWIKI_TEST_STUB_AGENT") == "1":
            return DeterministicStubAgent()
        raise IngestError(
            ERR_RUNTIME,
            "no agent bound (set --agent or LLMWIKI_TEST_STUB_AGENT=1)",
            EXIT_RUNTIME,
        )
    if ":" not in spec:
        raise IngestError(
            ERR_RUNTIME, f"--agent must be 'module:Class', got {spec!r}", EXIT_RUNTIME
        )
    mod_name, _, cls_name = spec.partition(":")
    try:
        mod = importlib.import_module(mod_name)
        cls = getattr(mod, cls_name)
    except (ImportError, AttributeError) as exc:
        raise IngestError(ERR_RUNTIME, f"agent load failed: {exc}", EXIT_RUNTIME)
    inst = cls()
    if not isinstance(inst, IngestAgent):
        raise IngestError(
            ERR_RUNTIME, f"{spec} is not an IngestAgent", EXIT_RUNTIME
        )
    return inst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wiki.ingest", add_help=True)
    parser.add_argument("slug_or_path")
    parser.add_argument("--wiki-root", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--agent", default=None)
    args = parser.parse_args(argv)

    try:
        if args.wiki_root:
            wiki_root = Path(args.wiki_root).resolve()
            if not (wiki_root / "SCHEMA.md").is_file():
                raise IngestError(
                    ERR_SCHEMA, f"not a wiki root: {wiki_root}", EXIT_SCHEMA
                )
        else:
            wiki_root = _find_wiki_root(Path.cwd())
        slug = _resolve_raw(wiki_root, args.slug_or_path)
        agent = _load_agent(args.agent)
        report = ingest_one(wiki_root, slug, agent, force=args.force)
    except IngestError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code

    n_concepts = sum(1 for p in report.touched_pages if "/concepts/" in str(p))
    n_entities = sum(1 for p in report.touched_pages if "/entities/" in str(p))
    print("INGEST COMPLETE")
    print(f"  source=1 concepts={n_concepts} entities={n_entities} "
          f"glossary_added={len(report.glossary_added)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

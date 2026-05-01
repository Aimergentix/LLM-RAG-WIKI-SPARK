"""M5 query orchestrator + CLI.

Accepts a natural-language question, scans the wiki for candidate pages,
delegates ranking and synthesis to a ``QueryAgent``, and optionally writes
an atomic synthesis page + index/log updates.

Per START-PROMPT §5 M5 contract; MASTER §6 W4 + §7 + §8 + §9.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

from . import _frontmatter as fm
from .init import substitute
from .query_agent import DeterministicStubQueryAgent, PageSummary, QueryAgent

ERR_SCHEMA = "[ERR_SCHEMA]"
ERR_SECURITY = "[ERR_SECURITY]"
ERR_RUNTIME = "[ERR_RUNTIME]"

EXIT_OK = 0
EXIT_SCHEMA = 2
EXIT_EXISTS = 3
EXIT_SECURITY = 4
EXIT_RUNTIME = 5

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


class QueryError(Exception):
    def __init__(self, code: str, msg: str, exit_code: int = EXIT_RUNTIME) -> None:
        super().__init__(f"{code}: {msg}")
        self.code = code
        self.exit_code = exit_code


class QueryReport(NamedTuple):
    answer: str
    sources_read: list[str]
    synthesis_path: Path | None


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
    raise QueryError(ERR_SCHEMA, f"no wiki root found from {start}", EXIT_SCHEMA)


def _validate_wiki_root(wiki_root: Path) -> None:
    wiki_root = wiki_root.resolve()
    for name in ("index.md", "SCHEMA.md"):
        if not (wiki_root / name).is_file():
            raise QueryError(
                ERR_SCHEMA, f"wiki root missing {name}: {wiki_root}", EXIT_SCHEMA
            )
    if not (wiki_root / ".wiki" / ".converted.json").is_file():
        raise QueryError(
            ERR_SCHEMA,
            f"wiki root missing .wiki/.converted.json: {wiki_root}",
            EXIT_SCHEMA,
        )


def slugify_question(question: str) -> str:
    """Derive a slug from a question string (≤64 chars, no path chars)."""
    s = _SLUG_STRIP_RE.sub("-", question.strip().lower()).strip("-")
    return (s or "query")[:64]


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise QueryError(ERR_SECURITY, f"invalid slug: {slug!r}", EXIT_SECURITY)
    if "/" in slug or ".." in slug:
        raise QueryError(ERR_SECURITY, f"slug contains path separators: {slug!r}", EXIT_SECURITY)


def _collect_candidates(wiki_root: Path) -> list[PageSummary]:
    """Scan wiki/**/*.md and return PageSummary list (relative POSIX paths)."""
    wiki_dir = wiki_root / "wiki"
    if not wiki_dir.is_dir():
        return []
    candidates: list[PageSummary] = []
    for p in sorted(wiki_dir.rglob("*.md")):
        if p.is_symlink():
            continue
        try:
            rel = p.relative_to(wiki_root).as_posix()
        except ValueError:
            continue
        text = p.read_text(encoding="utf-8")
        _, _, body = fm.split(text)
        # Extract title from H1 or first non-empty body line.
        title = p.stem
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("# "):
                title = s[2:].strip()
                break
        snippet = body.lstrip()[:300]
        candidates.append(PageSummary(path=rel, title=title, snippet=snippet))
    return candidates


def _read_pages(wiki_root: Path, paths: list[str]) -> dict[str, str]:
    """Read page contents for the ranked paths. Silently skips missing files."""
    result: dict[str, str] = {}
    for rel in paths:
        p = wiki_root / rel
        if p.is_file() and not p.is_symlink():
            result[rel] = p.read_text(encoding="utf-8")
    return result


def _render_synthesis_page(
    *,
    template_text: str,
    question: str,
    slug: str,
    date: str,
    answer: str,
    sources_read: list[str],
    confidence: str,
    follow_up: list[str],
) -> str:
    title = question[:80].rstrip("?").strip().title()
    mapping = {
        "DOMAIN": "",
        "DESCRIPTION": "",
        "DATE": date,
        "NAME": title,
        "TITLE": title,
        "SLUG": slug,
        "CONVERTER": "",
        "QUESTION": question,
        "ENTITY_TYPE": "",
    }
    rendered = substitute(template_text, mapping)

    # Patch frontmatter: add sources_read list.
    fm_data, fm_keys, body = fm.split(rendered)
    fm_data["sources_read"] = sources_read
    rendered = fm.render(fm_data, fm_keys, body)

    # Replace placeholder sections with agent output.
    if answer:
        rendered = re.sub(
            r"(## Answer\n).*?(?=\n## |\Z)",
            lambda m: m.group(1) + answer + "\n",
            rendered,
            count=1,
            flags=re.DOTALL,
        )
    if sources_read:
        lines = "\n".join(f"- {s}" for s in sources_read)
        rendered = re.sub(
            r"(## Sources Consulted\n).*?(?=\n## |\Z)",
            lambda m: m.group(1) + lines + "\n",
            rendered,
            count=1,
            flags=re.DOTALL,
        )
    if confidence:
        rendered = re.sub(
            r"(## Confidence\n).*?(?=\n## |\Z)",
            lambda m: m.group(1) + confidence + "\n",
            rendered,
            count=1,
            flags=re.DOTALL,
        )
    if follow_up:
        items = "\n".join(f"- {q}" for q in follow_up)
        rendered = re.sub(
            r"(## Follow-up Questions\n).*",
            lambda m: m.group(1) + items + "\n",
            rendered,
            count=1,
            flags=re.DOTALL,
        )

    return rendered


# ------------------------------------------------------ index update

_SYNTHESIS_SECTION = "## Synthesis"
_SYNTHESIS_PREFIX = "wiki/synthesis"


def _update_index(index_md: str, title: str, slug: str) -> str:
    """Insert/dedup synthesis link under ## Synthesis; append section if absent."""
    new_line = f"- [{title}]({_SYNTHESIS_PREFIX}/{slug}.md)"
    h_re = re.compile(r"^## Synthesis\s*$", re.MULTILINE)
    m = h_re.search(index_md)
    if m is None:
        tail = "\n## Synthesis\n\n" + new_line + "\n"
        text = index_md if index_md.endswith("\n") else index_md + "\n"
        return text + tail

    sec_start = m.end()
    next_h2 = re.compile(r"^## +", re.MULTILINE).search(index_md, sec_start + 1)
    sec_end = next_h2.start() if next_h2 else len(index_md)
    section = index_md[sec_start:sec_end]

    link_re = re.compile(
        rf"^- \[.+?\]\({re.escape(_SYNTHESIS_PREFIX)}/[^)]+\)$"
    )
    existing_lines = []
    other_lines = []
    for line in section.splitlines():
        if link_re.match(line.strip()):
            existing_lines.append(line.strip())
        else:
            other_lines.append(line)

    target_paths = {_link_target(l) for l in existing_lines}
    if _link_target(new_line) not in target_paths:
        existing_lines.append(new_line)
    existing_lines.sort(key=_link_target)

    rebuilt = "\n".join(other_lines).rstrip("\n")
    rebuilt = (rebuilt + "\n\n" if rebuilt else "\n") + "\n".join(existing_lines) + "\n"
    if next_h2 is not None:
        rebuilt += "\n"
    return index_md[:sec_start] + "\n" + rebuilt + index_md[sec_end:]


def _link_target(line: str) -> str:
    m = re.search(r"\(([^)]+)\)", line)
    return m.group(1) if m else line


# ---------------------------------------------------------- atomic writer

def _atomic_write_all(plan: dict[Path, str]) -> None:
    """2-phase atomic write: write all temps then replace. Same contract as M3."""
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


# ------------------------------------------------------------- query_one

def query_one(
    wiki_root: Path,
    question: str,
    agent: QueryAgent,
    *,
    file_as_synthesis: bool = False,
    slug: str | None = None,
    force: bool = False,
    today: str | None = None,
) -> QueryReport:
    # Check symlink before resolve (resolve() follows symlinks).
    if wiki_root.is_symlink():
        raise QueryError(ERR_SECURITY, f"wiki root is a symlink: {wiki_root}", EXIT_SECURITY)
    wiki_root = wiki_root.resolve()
    _validate_wiki_root(wiki_root)

    if not question or not question.strip():
        raise QueryError(ERR_SCHEMA, "question must be non-empty", EXIT_SCHEMA)

    # Slug derivation + validation.
    effective_slug = slug if slug is not None else agent.propose_slug(question=question)
    _validate_slug(effective_slug)

    # Safety: slug must not escape wiki/synthesis/.
    synth_dir = (wiki_root / "wiki" / "synthesis").resolve()
    synth_target = (synth_dir / f"{effective_slug}.md").resolve()
    try:
        synth_target.relative_to(synth_dir)
    except ValueError:
        raise QueryError(
            ERR_SECURITY,
            f"slug resolves outside wiki/synthesis/: {effective_slug}",
            EXIT_SECURITY,
        )

    if file_as_synthesis and synth_target.exists() and not force:
        raise QueryError(
            ERR_RUNTIME,
            f"synthesis page already exists: wiki/synthesis/{effective_slug}.md (use --force)",
            EXIT_EXISTS,
        )

    # Read required files.
    index_path = wiki_root / "index.md"
    log_path = wiki_root / "log.md"
    index_md = index_path.read_text(encoding="utf-8")
    log_md = log_path.read_text(encoding="utf-8")

    date = today or _today_iso()

    # Collect candidates and rank.
    candidates = _collect_candidates(wiki_root)
    ranked = agent.rank_pages(question=question, candidates=candidates)

    # Safety: ranked paths must stay inside wiki_root/wiki/.
    wiki_subdir = (wiki_root / "wiki").resolve()
    safe_ranked: list[str] = []
    for rel in ranked:
        resolved = (wiki_root / rel).resolve()
        try:
            resolved.relative_to(wiki_subdir)
            safe_ranked.append(rel)
        except ValueError:
            pass  # quietly drop paths that escape wiki/

    pages = _read_pages(wiki_root, safe_ranked)
    result = agent.synthesize(question=question, pages=pages)

    write_plan: dict[Path, str] = {}

    if file_as_synthesis:
        template_text = _read_template(wiki_root)
        synth_text = _render_synthesis_page(
            template_text=template_text,
            question=question,
            slug=effective_slug,
            date=date,
            answer=result["answer"],
            sources_read=result["sources_read"],
            confidence=result["confidence"],
            follow_up=result.get("follow_up", []),
        )
        write_plan[synth_target] = synth_text

        title = question[:80].rstrip("?").strip().title()
        new_index = _update_index(index_md, title, effective_slug)
        if new_index != index_md:
            write_plan[index_path] = new_index

    # Log line — always written.
    q_short = question[:80]
    if file_as_synthesis:
        log_line = f"## [{date}] query | {q_short} | filed as synthesis/{effective_slug}.md\n"
    else:
        log_line = f"## [{date}] query | {q_short} | not filed\n"
    new_log = log_md if log_md.endswith("\n") else log_md + "\n"
    new_log += log_line
    write_plan[log_path] = new_log

    # Safety: every write target must be inside wiki_root and outside protected dirs.
    for target in write_plan:
        try:
            rel = target.resolve().relative_to(wiki_root)
        except ValueError:
            raise QueryError(
                ERR_SECURITY, f"write outside wiki root: {target}", EXIT_SECURITY
            )
        first = rel.parts[0] if rel.parts else ""
        if first in {"raw", "entry", ".wiki"}:
            raise QueryError(
                ERR_SECURITY, f"write under read-only dir: {target}", EXIT_SECURITY
            )

    _atomic_write_all(write_plan)

    return QueryReport(
        answer=result["answer"],
        sources_read=result["sources_read"],
        synthesis_path=synth_target if file_as_synthesis else None,
    )


def _read_template(wiki_root: Path) -> str:
    """Locate synthesis.md template. Repo-root templates/ first; fallback to wiki-local."""
    # src/wiki/query.py -> repo root is two parents up.
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "templates" / "pages" / "synthesis.md",
        wiki_root / ".wiki" / "templates" / "pages" / "synthesis.md",
    ]
    for c in candidates:
        if c.is_file():
            return c.read_text(encoding="utf-8")
    raise QueryError(ERR_SCHEMA, "synthesis.md template not found", EXIT_SCHEMA)


def _today_iso() -> str:
    import datetime
    return datetime.date.today().isoformat()


# ------------------------------------------------------------------ CLI

def _load_agent(dotted: str) -> QueryAgent:
    """Load a QueryAgent from a dotted 'module:Class' string."""
    if ":" not in dotted:
        raise QueryError(
            ERR_RUNTIME,
            f"--agent must be 'dotted.module:ClassName', got: {dotted!r}",
            EXIT_RUNTIME,
        )
    mod_path, cls_name = dotted.rsplit(":", 1)
    try:
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        return cls()
    except Exception as exc:
        raise QueryError(ERR_RUNTIME, f"cannot load agent {dotted!r}: {exc}", EXIT_RUNTIME)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wiki.query",
        description="W4 query + optional synthesis writer",
    )
    parser.add_argument("question", help="Natural-language question")
    parser.add_argument("--wiki-root", metavar="DIR", help="Wiki root (auto-located if omitted)")
    parser.add_argument("--file", action="store_true", help="Write synthesis page")
    parser.add_argument("--slug", metavar="SLUG", help="Override derived slug")
    parser.add_argument("--force", action="store_true", help="Overwrite existing synthesis page")
    parser.add_argument("--agent", metavar="MOD:CLS", help="QueryAgent dotted path")
    args = parser.parse_args(argv)

    use_stub = os.environ.get("LLMWIKI_TEST_STUB_AGENT") == "1"

    if args.agent:
        try:
            agent: QueryAgent = _load_agent(args.agent)
        except QueryError as exc:
            print(exc, file=sys.stderr)
            return exc.exit_code
    elif use_stub:
        agent = DeterministicStubQueryAgent()
    else:
        print(
            f"{ERR_RUNTIME}: no agent bound — pass --agent dotted.path:Class "
            "or set LLMWIKI_TEST_STUB_AGENT=1",
            file=sys.stderr,
        )
        return EXIT_RUNTIME

    try:
        if args.wiki_root:
            wiki_root = Path(args.wiki_root)
        else:
            wiki_root = _find_wiki_root(Path.cwd())

        report = query_one(
            wiki_root,
            args.question,
            agent,
            file_as_synthesis=args.file,
            slug=args.slug,
            force=args.force,
        )
    except QueryError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code

    synth = str(report.synthesis_path.relative_to(wiki_root)) if report.synthesis_path else "not filed"
    print("QUERY COMPLETE")
    print(f"sources_read={len(report.sources_read)}")
    print(f"synthesis_path={synth}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

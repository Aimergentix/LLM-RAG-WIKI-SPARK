"""Wiki init entry point (M1).

Scaffolds a domain-specific wiki tree at a target path, hydrating the root
templates (SCHEMA.md, index.md, log.md) from ``templates/`` and seeding the
runtime state files under ``.wiki/``.

Public surface (consumed by M3, M5):
    substitute(text, mapping)   -> str
    init(domain, description, wiki_path=None, *, repo_root=None,
         today=None) -> Path

CLI:
    python -m wiki.init <domain> <description> [wiki_path]
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping

# Placeholders supported by ``substitute``. Per MASTER §7 (Wiki Schemas →
# Template placeholders). Reused by M3/M5.
SUPPORTED_PLACEHOLDERS: tuple[str, ...] = (
    "DOMAIN",
    "DESCRIPTION",
    "DATE",
    "NAME",
    "TITLE",
    "SLUG",
    "CONVERTER",
    "QUESTION",
    "ENTITY_TYPE",
)

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")
_SLUG_NONALNUM_RE = re.compile(r"[^a-z0-9]+")


class InitError(Exception):
    """Raised on path validation or scaffold failure."""


def slugify(text: str) -> str:
    """Lowercase, hyphen-separated slug. Empty input -> 'wiki'."""
    s = _SLUG_NONALNUM_RE.sub("-", text.strip().lower()).strip("-")
    return s or "wiki"


def substitute(text: str, mapping: Mapping[str, str]) -> str:
    """Replace ``{{KEY}}`` tokens in ``text`` using ``mapping``.

    Unknown keys raise ``KeyError`` so callers cannot silently leave
    placeholders unresolved in hydrated output.
    """
    def _repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in mapping:
            raise KeyError(key)
        return mapping[key]
    return _PLACEHOLDER_RE.sub(_repl, text)


def _default_repo_root() -> Path:
    # src/wiki/init.py -> repo root is two parents up.
    return Path(__file__).resolve().parents[2]


def _validate_path(target: Path) -> None:
    target_abs = target.resolve() if target.exists() else target.absolute()
    cwd = Path.cwd().resolve()

    # Order: most-specific structural checks first so the user gets the
    # informative reason. ``cwd`` and any ancestor of cwd necessarily exist,
    # so the existence check would always swallow them otherwise.
    if target_abs == cwd:
        raise InitError(f"target path equals current working directory: {target_abs}")
    try:
        cwd.relative_to(target_abs)
    except ValueError:
        pass
    else:
        raise InitError(f"target path is an ancestor of cwd: {target_abs}")
    if any(part == ".git" for part in target_abs.parts):
        raise InitError(f"target path is under .git: {target_abs}")
    if target.exists():
        raise InitError(f"target path already exists: {target_abs}")


def _hydrate(template_path: Path, dest_path: Path, mapping: Mapping[str, str]) -> None:
    text = template_path.read_text(encoding="utf-8")
    rendered = substitute(text, mapping)
    dest_path.write_text(rendered, encoding="utf-8")


def init(
    domain: str,
    description: str,
    wiki_path: str | os.PathLike[str] | None = None,
    *,
    repo_root: Path | None = None,
    today: str | None = None,
) -> Path:
    """Scaffold a wiki instance. Returns the absolute target path."""
    if not domain or not domain.strip():
        raise InitError("domain name must not be empty")
    if not description or not description.strip():
        raise InitError("description must not be empty")

    repo = (repo_root or _default_repo_root()).resolve()
    templates = repo / "templates"
    if not templates.is_dir():
        raise InitError(f"templates directory missing: {templates}")

    slug = slugify(domain)
    target = Path(wiki_path) if wiki_path else Path(f"./wiki-{slug}")
    _validate_path(target)

    date = today or _dt.date.today().isoformat()
    mapping = {
        "DOMAIN": domain.strip(),
        "DESCRIPTION": description.strip(),
        "DATE": date,
        "SLUG": slug,
        # Page-template placeholders are not used by init-time hydration but
        # must be accepted by ``substitute`` callers in M3/M5. Provide
        # neutral defaults so ad-hoc invocations don't crash.
        "NAME": domain.strip(),
        "TITLE": domain.strip(),
        "CONVERTER": "copy",
        "QUESTION": "",
        "ENTITY_TYPE": "person",
    }

    target_abs = target.absolute()
    subdirs: Iterable[str] = (
        "entry",
        "raw/assets",
        "wiki/concepts",
        "wiki/entities",
        "wiki/sources",
        "wiki/synthesis",
        ".wiki",
    )
    target_abs.mkdir(parents=True, exist_ok=False)
    for sub in subdirs:
        (target_abs / sub).mkdir(parents=True, exist_ok=False)

    for name in ("SCHEMA.md", "index.md", "log.md"):
        _hydrate(templates / name, target_abs / name, mapping)

    (target_abs / ".wiki" / ".converted.json").write_text("{}\n", encoding="utf-8")
    (target_abs / ".wiki" / ".status.json").write_text("{}\n", encoding="utf-8")

    return target_abs


def _print_banner(target: Path) -> None:
    print(f"wiki initialized at: {target}")
    print("next steps:")
    print("  - drop source files into entry/")
    print("  - run autoconvert (M2)")
    print("  - run ingest (M3)")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print('Usage: init <domain_name> <description> [wiki_path]', file=sys.stderr)
        return 0 if args[:1] in (["-h"], ["--help"]) else 2
    if args[0] != "init":
        print(f"unknown command: {args[0]} (expected 'init')", file=sys.stderr)
        return 2
    rest = args[1:]
    if len(rest) < 2 or len(rest) > 3:
        print("init: expected <domain_name> <description> [wiki_path]", file=sys.stderr)
        return 2
    domain, description = rest[0], rest[1]
    wiki_path = rest[2] if len(rest) == 3 else None
    try:
        target = init(domain, description, wiki_path)
    except InitError as exc:
        print(f"init: {exc}", file=sys.stderr)
        return 1
    _print_banner(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tiny YAML-frontmatter reader/writer for wiki pages.

Stdlib only. Handles the narrow subset used by wiki page templates:
scalar ``key: value`` lines plus list-style ``key: [a, b]`` or
``key: []``. Preserves unknown keys and key order on round-trip.
"""

from __future__ import annotations

from typing import Any


def split(text: str) -> tuple[dict[str, Any], list[str], str]:
    """Return ``(frontmatter, ordered_keys, body)``.

    If the text has no ``---`` fence at the top, returns empty FM and the
    whole text as body.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, [], text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, [], text
    fm: dict[str, Any] = {}
    keys: list[str] = []
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            continue
        k, _, v = raw.partition(":")
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            fm[k] = [p.strip() for p in inner.split(",") if p.strip()] if inner else []
        else:
            # Strip surrounding quotes if present.
            if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
                v = v[1:-1]
            fm[k] = v
        keys.append(k)
    body = "\n".join(lines[end + 1 :])
    # Preserve trailing newline if original had one.
    if text.endswith("\n") and not body.endswith("\n"):
        body += "\n"
    return fm, keys, body


def render(fm: dict[str, Any], keys: list[str], body: str) -> str:
    """Serialize frontmatter + body. ``keys`` orders the output."""
    out = ["---"]
    seen: set[str] = set()
    for k in keys:
        if k in fm:
            out.append(_render_kv(k, fm[k]))
            seen.add(k)
    for k, v in fm.items():
        if k not in seen:
            out.append(_render_kv(k, v))
    out.append("---")
    text = "\n".join(out) + "\n" + body
    if not text.endswith("\n"):
        text += "\n"
    return text


def _render_kv(k: str, v: Any) -> str:
    if isinstance(v, list):
        inner = ", ".join(str(x) for x in v)
        return f"{k}: [{inner}]"
    return f"{k}: {v}"

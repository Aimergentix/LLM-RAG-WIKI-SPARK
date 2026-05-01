"""M8 heading-aware Markdown chunker (pure stdlib).

Per START-PROMPT §5 M8 contract; MASTER §7 (Stable chunk ID derivation).

Algorithm:

* Walk the document line-by-line; ATX headings ``#`` … ``######`` open a
  new heading scope and reset the heading-path stack at that level.
* Body lines under each heading are split into paragraphs (blank-line
  separated). Paragraphs are accumulated greedily into a chunk until
  adding the next paragraph would exceed ``max_chars``.
* If a single paragraph exceeds ``max_chars`` it is hard-split on
  whitespace boundaries.
* Within one heading, the *final* chunk may be shorter than
  ``min_chars``; intermediate chunks are not emitted until they reach
  ``min_chars`` (subsequent paragraphs are appended even if doing so
  pushes the running buffer past ``max_chars`` slightly — but never
  more than 1.25x ``max_chars`` so that downstream embedders stay
  inside their token budget).
* Code fences (``\\`\\`\\``` / ``~~~``) are kept atomic — never split,
  and their internal blank lines never end a chunk.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^(```|~~~)")


@dataclass(frozen=True)
class Chunk:
    rel_path: str
    heading_path: str
    chunk_index: int
    text: str
    chunk_hash: str
    chunk_id: str


def _normalize(text: str) -> str:
    """Normalize line endings (LF) and strip a trailing form-feed/BOM."""
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_frontmatter(text: str) -> str:
    """Remove a YAML ``---`` frontmatter block at the very top, if present."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :])
    return text  # unterminated → leave as-is


def _split_paragraphs(body_lines: list[str]) -> list[str]:
    """Group body lines into paragraphs separated by blank lines.

    Code fences and their interior content are atomic — blank lines
    inside a fence do not end a paragraph.
    """
    paragraphs: list[str] = []
    buf: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in body_lines:
        if not in_fence and _FENCE_RE.match(line):
            in_fence = True
            fence_marker = _FENCE_RE.match(line).group(1)  # type: ignore[union-attr]
            buf.append(line)
            continue
        if in_fence:
            buf.append(line)
            if line.strip().startswith(fence_marker):
                in_fence = False
            continue
        if line.strip() == "":
            if buf:
                paragraphs.append("\n".join(buf).strip("\n"))
                buf = []
            continue
        buf.append(line)
    if buf:
        paragraphs.append("\n".join(buf).strip("\n"))
    return [p for p in paragraphs if p.strip()]


def _hard_split_paragraph(p: str, max_chars: int) -> list[str]:
    """Split an oversize paragraph on whitespace boundaries."""
    pieces: list[str] = []
    words = p.split(" ")
    current = ""
    for w in words:
        candidate = w if not current else current + " " + w
        if len(candidate) > max_chars and current:
            pieces.append(current)
            current = w
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _flush(chunks_out: list[str], buf: list[str]) -> None:
    if buf:
        chunks_out.append("\n\n".join(buf).strip())
        buf.clear()


def _chunk_section(paragraphs: list[str], min_chars: int, max_chars: int) -> list[str]:
    """Pack paragraphs into chunks honoring min/max bounds.

    The final chunk may be below ``min_chars``; intermediate chunks are
    always at least ``min_chars`` (best-effort — if a single oversize
    paragraph is hard-split, the resulting tail piece may be small but
    is treated as terminal for this section).
    """
    if not paragraphs:
        return []
    # Pre-expand any paragraph longer than max_chars into hard splits.
    expanded: list[str] = []
    for p in paragraphs:
        if len(p) > max_chars:
            expanded.extend(_hard_split_paragraph(p, max_chars))
        else:
            expanded.append(p)

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    soft_cap = int(max_chars * 1.25)
    for p in expanded:
        sep = 2 if buf else 0  # for the "\n\n" join
        prospective = buf_len + sep + len(p)
        if not buf:
            buf.append(p)
            buf_len = len(p)
            continue
        if buf_len < min_chars:
            # Must keep growing toward min_chars.
            buf.append(p)
            buf_len = prospective
            if buf_len >= max_chars:
                _flush(chunks, buf)
                buf_len = 0
            continue
        # buf_len >= min_chars: prefer to flush before exceeding max_chars.
        if prospective <= max_chars:
            buf.append(p)
            buf_len = prospective
        elif prospective <= soft_cap and len(buf) == 1:
            # Single paragraph already at/over min_chars; allow one extra
            # paragraph rather than emit a tiny one. Otherwise flush.
            buf.append(p)
            buf_len = prospective
            _flush(chunks, buf)
            buf_len = 0
        else:
            _flush(chunks, buf)
            buf.append(p)
            buf_len = len(p)
    _flush(chunks, buf)
    return chunks


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def chunk_markdown(
    text: str,
    *,
    rel_path: str,
    collection_name: str,
    min_chars: int,
    max_chars: int,
) -> list[Chunk]:
    """Heading-aware chunker → deterministic :class:`Chunk` list.

    Stable chunk ID derivation (MASTER §7)::

        chunk_hash = sha256(normalized_chunk_text)
        chunk_id   = sha256(collection_name + rel_path + heading_path
                            + chunk_index + chunk_hash)
    """
    if min_chars < 1:
        raise ValueError("min_chars must be >= 1")
    if max_chars <= min_chars:
        raise ValueError("max_chars must be > min_chars")

    text = _strip_frontmatter(_normalize(text))
    lines = text.split("\n")

    # Walk the lines, grouping into (heading_path, body_lines) sections.
    sections: list[tuple[str, list[str]]] = []
    heading_stack: list[tuple[int, str]] = []  # (level, title)
    current_body: list[str] = []
    current_path = ""
    in_fence = False
    fence_marker = ""

    def _path_str(stack: list[tuple[int, str]]) -> str:
        return " > ".join(t for _, t in stack)

    for line in lines:
        if not in_fence and _FENCE_RE.match(line):
            in_fence = True
            fence_marker = _FENCE_RE.match(line).group(1)  # type: ignore[union-attr]
            current_body.append(line)
            continue
        if in_fence:
            current_body.append(line)
            if line.strip().startswith(fence_marker):
                in_fence = False
            continue
        m = _HEADING_RE.match(line)
        if m:
            # Close out the previous section.
            sections.append((current_path, current_body))
            current_body = []
            level = len(m.group(1))
            title = m.group(2).strip()
            # Pop stack to parent of this level.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            current_path = _path_str(heading_stack)
        else:
            current_body.append(line)
    sections.append((current_path, current_body))

    # Build ordered chunk records across sections.
    out: list[Chunk] = []
    chunk_index = 0
    for heading_path, body_lines in sections:
        paragraphs = _split_paragraphs(body_lines)
        chunk_texts = _chunk_section(paragraphs, min_chars, max_chars)
        for ct in chunk_texts:
            normalized = ct.replace("\r\n", "\n").replace("\r", "\n")
            chunk_hash = _sha256(normalized)
            id_payload = (
                f"{collection_name}\x00{rel_path}\x00{heading_path}"
                f"\x00{chunk_index}\x00{chunk_hash}"
            )
            chunk_id = _sha256(id_payload)
            out.append(
                Chunk(
                    rel_path=rel_path,
                    heading_path=heading_path,
                    chunk_index=chunk_index,
                    text=normalized,
                    chunk_hash=chunk_hash,
                    chunk_id=chunk_id,
                )
            )
            chunk_index += 1
    return out

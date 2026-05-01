"""M8 acceptance tests — chunker.

Covers contract criteria 1–4.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rag.chunker import chunk_markdown  # noqa: E402


# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_kw: object) -> None:
        raise OSError("network blocked in tests")

    monkeypatch.setattr(socket, "socket", _raise)


SAMPLE = """\
# Top

Intro paragraph that is reasonably long so it will satisfy the minimum
character threshold for a chunk in the small-bounds test setup. We add
several extra sentences to make sure we exceed the minimum cleanly.

## Sub A

Body of sub A. This is a long enough paragraph to be a chunk on its own,
once we ensure that we add enough text and explanatory padding to bring
us over the minimum chunk size in the test config used below.

Second paragraph under Sub A with even more padding text included so
that the chunker has to consider whether to combine paragraphs into
one chunk or emit two separate chunks under the same heading path.

## Sub B

Short.
"""


# ---------------------------------------------------------------- tests


def test_chunker_is_deterministic() -> None:
    """Criterion 1: same input → identical chunk_id / chunk_hash lists."""
    a = chunk_markdown(
        SAMPLE,
        rel_path="example.md",
        collection_name="generic",
        min_chars=80,
        max_chars=400,
    )
    b = chunk_markdown(
        SAMPLE,
        rel_path="example.md",
        collection_name="generic",
        min_chars=80,
        max_chars=400,
    )
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert [c.chunk_hash for c in a] == [c.chunk_hash for c in b]
    assert [c.text for c in a] == [c.text for c in b]


def test_chunker_honors_min_max() -> None:
    """Criterion 2: no chunk exceeds max_chars; non-final under heading >= min."""
    chunks = chunk_markdown(
        SAMPLE,
        rel_path="example.md",
        collection_name="generic",
        min_chars=80,
        max_chars=400,
    )
    # No chunk wildly exceeds max_chars (1.25x soft cap allowed).
    for c in chunks:
        assert len(c.text) <= int(400 * 1.25)

    # Group by heading_path; non-final chunks under the same heading
    # must be >= min_chars.
    by_heading: dict[str, list[int]] = {}
    for c in chunks:
        by_heading.setdefault(c.heading_path, []).append(len(c.text))
    for heading, sizes in by_heading.items():
        if len(sizes) < 2:
            continue
        for s in sizes[:-1]:
            assert s >= 80, f"non-final chunk under {heading!r} below min_chars: {s}"


def test_chunker_heading_path_reflects_ancestry() -> None:
    """Criterion 3: heading_path = nearest enclosing H1 > H2 > … chain."""
    text = """\
# H1

Body for H1, padded to be a real chunk with multiple sentences so the
chunker actually emits something for the top-level heading scope.

## H2

Body for H2 also padded enough to cross the minimum size threshold and
emit a chunk under the H1 > H2 heading path with predictable content.

### H3

Body for H3 padded to cross the chunker minimum so it materializes as
a chunk under the H1 > H2 > H3 heading path with the expected ancestry.
"""
    chunks = chunk_markdown(
        text,
        rel_path="x.md",
        collection_name="generic",
        min_chars=80,
        max_chars=400,
    )
    paths = {c.heading_path for c in chunks}
    assert "H1" in paths
    assert "H1 > H2" in paths
    assert "H1 > H2 > H3" in paths


def test_chunker_id_derivation_matches_master_spec() -> None:
    """Criterion 4: chunk_id = sha256(coll + rel + heading + idx + chunk_hash)."""
    import hashlib

    chunks = chunk_markdown(
        SAMPLE,
        rel_path="example.md",
        collection_name="generic",
        min_chars=80,
        max_chars=400,
    )
    assert chunks
    for c in chunks:
        expected_hash = hashlib.sha256(c.text.encode("utf-8")).hexdigest()
        assert c.chunk_hash == expected_hash
        payload = (
            f"generic\x00example.md\x00{c.heading_path}"
            f"\x00{c.chunk_index}\x00{c.chunk_hash}"
        )
        expected_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        assert c.chunk_id == expected_id


def test_chunker_strips_frontmatter() -> None:
    """Frontmatter must not contribute to chunk text."""
    text = """\
---
type: source
title: Hello
---

# H1

Body content padded sufficiently to produce a chunk under the H1
heading path so we can assert nothing from the frontmatter leaks in.
"""
    chunks = chunk_markdown(
        text,
        rel_path="x.md",
        collection_name="generic",
        min_chars=40,
        max_chars=400,
    )
    assert chunks
    joined = "\n".join(c.text for c in chunks)
    assert "type: source" not in joined
    assert "title: Hello" not in joined


def test_chunker_keeps_code_fence_atomic() -> None:
    """Code fences must not be split mid-block."""
    text = """\
# H1

Intro paragraph long enough to satisfy the min threshold for a chunk
on its own ahead of the code fence below.

```python
def f():
    return 1


def g():
    return 2
```
"""
    chunks = chunk_markdown(
        text,
        rel_path="x.md",
        collection_name="generic",
        min_chars=20,
        max_chars=400,
    )
    fence_chunks = [c for c in chunks if "```" in c.text]
    for c in fence_chunks:
        # Each fence must be balanced (an even number of fence markers).
        assert c.text.count("```") % 2 == 0


def test_chunker_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        chunk_markdown(
            "x",
            rel_path="x.md",
            collection_name="g",
            min_chars=0,
            max_chars=10,
        )
    with pytest.raises(ValueError):
        chunk_markdown(
            "x",
            rel_path="x.md",
            collection_name="g",
            min_chars=10,
            max_chars=10,
        )

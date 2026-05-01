"""Agent seam for M3 ingest.

W3 has three sub-steps that require an LLM (takeaways, contradictions,
vision resolution) plus two more that benefit from one (cross-ref planning,
glossary detection). The deterministic core in ``wiki.ingest`` calls into
this seam; production binds a real LLM-backed implementation, tests bind
``DeterministicStubAgent`` (or a spy subclass).

Per START-PROMPT §5 M3 contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, TypedDict


class TouchedPage(TypedDict, total=False):
    kind: Literal["concept", "entity"]
    slug: str
    title: str
    depends_on: list[str]
    merge_md: str
    entity_type: str  # entities only; defaults to "person"


class Contradiction(TypedDict):
    with_source_slug: str
    claim: str
    counter_claim: str


class IngestAgent(ABC):
    @abstractmethod
    def extract_takeaways(
        self, *, raw_md: str, schema_md: str, index_md: str
    ) -> list[str]:
        """Return 3–6 short takeaways from the raw source."""

    @abstractmethod
    def plan_crossrefs(
        self,
        *,
        raw_md: str,
        takeaways: list[str],
        existing_pages: dict[str, str],
    ) -> list[TouchedPage]:
        """Return 0–10 ``TouchedPage`` dicts with ``depends_on`` edges."""

    @abstractmethod
    def find_contradictions(
        self, *, page_slug: str, page_md: str, new_fragment: str
    ) -> list[Contradiction]:
        """Return contradictions between existing page and new fragment."""

    @abstractmethod
    def detect_glossary_terms(
        self,
        *,
        raw_md: str,
        takeaways: list[str],
        existing_terms: set[str],
    ) -> list[tuple[str, str]]:
        """Return ``(term, definition)`` pairs not already in glossary."""

    @abstractmethod
    def resolve_vision(self, *, marker_path: Path, asset_path: Path | None) -> str:
        """Return text replacing a ``<!-- needs-vision: ... -->`` marker."""


class DeterministicStubAgent(IngestAgent):
    """Test-only stub. Pure function of inputs; no I/O, no network."""

    def extract_takeaways(self, *, raw_md, schema_md, index_md):
        # Pick the first 3 non-empty, non-heading, non-frontmatter lines.
        out: list[str] = []
        in_fm = False
        for line in raw_md.splitlines():
            s = line.strip()
            if s == "---":
                in_fm = not in_fm
                continue
            if in_fm or not s or s.startswith("#") or s.startswith("<!--"):
                continue
            out.append(s.lstrip("-* ").rstrip())
            if len(out) == 3:
                break
        while len(out) < 3:
            out.append(f"stub-takeaway-{len(out) + 1}")
        return out

    def plan_crossrefs(self, *, raw_md, takeaways, existing_pages):
        # Default: no cross-refs. Tests subclass to provide a plan.
        return []

    def find_contradictions(self, *, page_slug, page_md, new_fragment):
        return []

    def detect_glossary_terms(self, *, raw_md, takeaways, existing_terms):
        return []

    def resolve_vision(self, *, marker_path, asset_path):
        ref = asset_path if asset_path is not None else marker_path
        return f"[vision-stub] description for {ref.name}"

"""Agent seam for M5 query + synthesis.

W4 has three sub-steps that require an LLM: ranking candidate pages,
synthesising an answer with citations, and proposing a slug for the
synthesis page. The deterministic core in ``wiki.query`` calls into
this seam; production binds a real LLM-backed implementation, tests
bind ``DeterministicStubQueryAgent`` (or a spy subclass).

Per START-PROMPT §5 M5 contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class PageSummary(TypedDict):
    path: str    # relative path from wiki_root (POSIX)
    title: str
    snippet: str  # first ≤300 chars of body


class SynthesisResult(TypedDict):
    answer: str
    sources_read: list[str]   # subset of candidate paths passed to synthesize
    confidence: str           # free text, e.g. "medium — 2 sources"
    follow_up: list[str]      # 1–4 items


class QueryAgent(ABC):
    @abstractmethod
    def rank_pages(
        self, *, question: str, candidates: list[PageSummary]
    ) -> list[str]:
        """Return ≤7 relative paths (from candidates) most relevant to the question."""

    @abstractmethod
    def synthesize(
        self, *, question: str, pages: dict[str, str]
    ) -> SynthesisResult:
        """Return a synthesised answer given full page contents keyed by relative path."""

    @abstractmethod
    def propose_slug(self, *, question: str) -> str:
        """Return a valid slug for the synthesis page (no path separators, ≤64 chars)."""


class DeterministicStubQueryAgent(QueryAgent):
    """Test-only stub. Pure function of inputs; no I/O, no network."""

    def rank_pages(self, *, question: str, candidates: list[PageSummary]) -> list[str]:
        # Return all candidates (up to 7) in their listed order.
        return [c["path"] for c in candidates[:7]]

    def synthesize(self, *, question: str, pages: dict[str, str]) -> SynthesisResult:
        sources = sorted(pages.keys())
        answer_parts = [f"Stub answer for: {question}"]
        for path, content in sorted(pages.items()):
            # Extract first non-empty body line as a citation token.
            for line in content.splitlines():
                s = line.strip()
                if s and not s.startswith("---") and not s.startswith("#"):
                    answer_parts.append(f"From [{path}]: {s[:80]}")
                    break
        return SynthesisResult(
            answer="\n".join(answer_parts),
            sources_read=sources,
            confidence="low — stub agent",
            follow_up=["What else?"],
        )

    def propose_slug(self, *, question: str) -> str:
        import re
        s = re.sub(r"[^a-z0-9]+", "-", question.strip().lower()).strip("-")
        return (s or "query")[:64]

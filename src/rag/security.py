"""M9 Security utilities.

Centralizes prompt-injection markers and shared safety logic per MASTER §8.
"""

INJECTION_MARKERS = (
    "ignore rules",
    "print secrets",
    "disable guardrails",
    "change system behavior",
    "<!-- prompt_injection_marker -->",
)


def is_injection_flagged(text: str) -> bool:
    """Return True if text contains any known injection markers."""
    low_text = text.lower()
    return any(marker in low_text for marker in INJECTION_MARKERS)
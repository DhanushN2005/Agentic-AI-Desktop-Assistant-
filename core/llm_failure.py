"""Recognise text that is a *failure message*, not a real model answer.

When no provider can answer, ``Brain.ask`` returns a friendly fallback (a web-search blurb or an
"unavailable" notice). That is fine to speak to a user but must never be written into a source
file or parsed as data - an ``app.js`` containing "I've searched for you..." was once reported as
a successful build.
"""
from __future__ import annotations

FAILURE_MARKERS = (
    "All AI providers are unavailable",
    "I've searched for you,",
    "Based on my web search",
    "I couldn't get a vision model",
    "Sorry, I couldn't get an answer from my language model",
)


def is_failure_text(text) -> bool:
    """True for empty text or a known provider-failure/fallback message."""
    if not isinstance(text, str) or not text.strip():
        return True
    head = text.strip()[:400]
    return any(marker in head for marker in FAILURE_MARKERS)


def substantive_code(text: str, min_lines: int = 1) -> bool:
    """A file body with at least ``min_lines`` non-blank, non-comment-only lines."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.strip().startswith(("//", "#", "/*", "*", "<!--"))]
    return len(lines) >= min_lines

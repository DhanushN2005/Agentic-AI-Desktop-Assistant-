"""Persistent persona loader.

Persona files are plain Markdown owned by the user, loaded once per
conversation and injected into the system prompt. No vector DB, no indexing.
"""
from __future__ import annotations

import os
from pathlib import Path

SECTION_LIMIT = 2000
_SECTIONS = (("SOUL", "SOUL.md"), ("MEMORY", "MEMORY.md"), ("USER", "USER.md"))


def persona_root() -> Path:
    """Directory holding the default persona files."""
    env = os.getenv("FLEXIE_PERSONA_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent / "data" / "persona"


def _read_limited(path: Path, limit: int = SECTION_LIMIT) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n...[truncated]"
    return text


def load_persona(name: str | None = None) -> str:
    """Return the persona block, or an empty string when disabled/missing.

    ``name="none"`` disables persona injection. Named personas live under
    ``<persona_root>/personas/<name>/``.
    """
    if name == "none":
        return ""
    name = name or os.getenv("FLEXIE_PERSONA", "")
    root = persona_root()
    if name and name not in ("default", "none"):
        named = root / "personas" / name
        if named.is_dir():
            root = named

    parts = []
    for label, filename in _SECTIONS:
        text = _read_limited(root / filename)
        if text:
            parts.append(f"## {label}\n{text}")
    return "\n\n".join(parts)


# Facts about itself the model must not invent around (live details come from core/self_model.py).
SELF_FACTS = (
    "ABOUT YOURSELF: You are Flexie, a voice and text desktop assistant running on the user's computer. "
    "You are not ChatGPT or GPT-4, and you do not know which language model is answering you: if asked, "
    "say the underlying model can vary and that the user can ask 'what model are you using'. "
    "Never claim to have done something (opened an app, saved a file, downloaded an image) unless you were "
    "told it happened; never promise a feature you were not told you have."
)


def compose_system_prompt(base: str, name: str | None = None) -> str:
    """Append the persona block to a base system prompt."""
    persona = load_persona(name)
    if not persona:
        return base
    return f"{base}\n\nPERSISTENT PERSONA (user-owned, edit freely):\n{persona}"

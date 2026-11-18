"""Helpers for literal substring matching in SQLite LIKE queries."""

LIKE_ESCAPE = "!"


def like_contains(text: str) -> str:
    """Pattern matching ``text`` literally anywhere. Use with ``ESCAPE '!'``."""
    esc = text.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{esc}%"

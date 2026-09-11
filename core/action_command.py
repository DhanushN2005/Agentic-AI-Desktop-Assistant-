"""
ActionCommand — Structured internal command representation.

Replaces fragile colon-separated strings like 'set_brightness:45' with a
typed object. Only used internally by the DAG planner; always converted to
natural language via natural_language() before reaching the intent router,
preserving full backward compatibility with existing routing logic.
"""
from typing import Any, Optional


class ActionCommand:
    """
    Represents a structured command with an explicit intent and parameters.

    Examples:
        ActionCommand(intent="brightness", value=45)
            → natural_language() → "set brightness 45"

        ActionCommand(intent="close_app", target="notepad")
            → natural_language() → "close app notepad"
    """

    def __init__(
        self,
        intent: str,
        value: Any = None,
        target: str = "",
        raw: str = ""
    ):
        # intent: the action name, e.g. "brightness", "close_app", "search_google"
        self.intent = intent
        # value: numeric or string parameter, e.g. 45, "python tutorials"
        self.value = value
        # target: optional secondary target, e.g. app name
        self.target = target
        # raw: original raw string if parsing was ambiguous (preserved for logging)
        self.raw = raw

    def natural_language(self) -> str:
        """
        Converts the structured command to a router-compatible natural language string.

        This is the single conversion point where internal format leaves the planner.
        Replaces underscores with spaces and joins parts with a single space.
        """
        parts = [self.intent.replace("_", " ")]
        if self.value is not None:
            parts.append(str(self.value))
        if self.target:
            parts.append(self.target)
        return " ".join(parts)

    @staticmethod
    def from_string(raw: str) -> "ActionCommand":
        """
        Parses a colon-separated internal command string into an ActionCommand.

        Examples:
            "set_brightness:45"     → ActionCommand(intent="set_brightness", value="45")
            "close_app:notepad"     → ActionCommand(intent="close_app", target="notepad")
            "open notepad"          → ActionCommand(intent="open notepad", raw="open notepad")
        """
        if ":" in raw:
            parts = raw.split(":", 1)
            return ActionCommand(
                intent=parts[0].strip(),
                value=parts[1].strip(),
                raw=raw
            )
        return ActionCommand(intent=raw, raw=raw)

    def __str__(self) -> str:
        return (
            f"ActionCommand(intent={self.intent!r}, "
            f"value={self.value!r}, target={self.target!r})"
        )

    def __repr__(self) -> str:
        return self.__str__()

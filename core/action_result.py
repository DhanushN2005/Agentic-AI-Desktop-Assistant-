"""
ActionResult — Structured return type for all Flexie action handlers.

Replaces raw True/False/None returns with a typed, inspectable result object
that the workflow verification layer can reliably consume.

Backward compatible: ActionResult is truthy when successful (__bool__),
so existing code that does `if result:` continues to work.
"""
import time
from typing import Any, Optional


class ActionResult:
    """Structured result returned by action handlers and _blocking_execute."""

    def __init__(
        self,
        success: bool,
        message: str = "",
        duration: float = 0.0,
        intent: str = "",
        data: Optional[dict] = None
    ):
        self.success = success
        self.message = message
        self.duration = duration
        self.intent = intent
        self.data = data or {}
        self.timestamp = time.time()

    # --- Backward-compat: ActionResult is truthy when successful ---
    def __bool__(self) -> bool:
        return self.success

    def __str__(self) -> str:
        status = "OK" if self.success else "FAIL"
        return (
            f"ActionResult({status} | intent={self.intent!r} | "
            f"duration={self.duration:.2f}s | msg={self.message!r})"
        )

    def __repr__(self) -> str:
        return self.__str__()

    # --- Factory helpers ---
    @staticmethod
    def ok(
        message: str = "",
        intent: str = "",
        data: Optional[dict] = None,
        duration: float = 0.0
    ) -> "ActionResult":
        """Convenience factory for a successful result."""
        return ActionResult(
            success=True, message=message,
            intent=intent, data=data or {}, duration=duration
        )

    @staticmethod
    def fail(
        message: str = "",
        intent: str = "",
        data: Optional[dict] = None,
        duration: float = 0.0
    ) -> "ActionResult":
        """Convenience factory for a failed result."""
        return ActionResult(
            success=False, message=message,
            intent=intent, data=data or {}, duration=duration
        )

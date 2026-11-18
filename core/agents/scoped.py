"""A tool registry view that only exposes (and only executes) an allowlisted set of tools.

Specialists used to receive the whole registry and merely be *told* which tools they
should use. A model that ignored (or was tricked out of) that instruction could call
anything. ``ScopedToolRegistry`` makes the scope a hard boundary: tools outside it are
neither listed to the model nor executable.
"""
from __future__ import annotations

from typing import Any

from core.action_result import ActionResult


class ScopedToolRegistry:
    def __init__(self, registry: Any, allowed: set[str] | list[str], extra: dict[str, Any] | None = None):
        self._registry = registry
        self._allowed = set(allowed)
        # Virtual tools that exist only for this scope (e.g. the lead's ``delegate``).
        self._extra = dict(extra or {})

    @property
    def allowed(self) -> set[str]:
        return set(self._allowed) | set(self._extra)

    def get(self, name: str):
        if name in self._extra:
            return self._extra[name]
        if name in self._allowed and self._registry is not None:
            return self._registry.get(name)
        return None

    def list_tools(self, tag: str | None = None, enabled_only: bool = True) -> list:
        tools = [t for name in sorted(self._allowed)
                 if self._registry is not None and (t := self._registry.get(name)) is not None]
        tools.extend(self._extra.values())
        if enabled_only:
            tools = [t for t in tools if getattr(t, "enabled", True)]
        if tag:
            tools = [t for t in tools if tag in getattr(t, "tags", [])]
        return tools

    def list_tool_names(self, tag: str | None = None) -> list[str]:
        return [t.name for t in self.list_tools(tag)]

    def execute(self, name: str, args: dict, timeout: float | None = None) -> ActionResult:
        if name in self._extra:
            tool = self._extra[name]
            ok, err = tool.validate_args(args or {})
            if not ok:
                return ActionResult.fail(message=f"Invalid args: {err}", intent=name)
            try:
                result = tool.execute_fn(**(args or {}))
            except Exception as e:  # a failing virtual tool must not kill the agent loop
                return ActionResult.fail(message=f"Tool '{name}' error: {e}", intent=name)
            return result if isinstance(result, ActionResult) else ActionResult.ok(message=str(result), intent=name)
        if name not in self._allowed:
            return ActionResult.fail(
                message=f"Tool '{name}' is outside this agent's scope.", intent=name,
                data={"out_of_scope": True},
            )
        return self._registry.execute(name, args, timeout=timeout)

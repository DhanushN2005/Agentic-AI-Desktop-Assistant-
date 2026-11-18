"""Capability vocabulary and policy for tools and skills."""
from __future__ import annotations

KNOWN_CAPABILITIES = frozenset(
    {
        "network:fetch",
        "network:listen",
        "filesystem:read",
        "filesystem:write",
        "shell:execute",
        "memory:read",
        "memory:write",
        "engine:inference",
    }
)

DANGEROUS_CAPABILITIES = frozenset({"shell:execute", "network:listen", "filesystem:write"})


class CapabilityPolicy:
    """Validate declared capabilities against allowed/denied sets."""

    # No built-in tool needs to open a listening socket: deny it unless an operator opts in by
    # passing ``denied=set()`` explicitly. Unknown capability names are always denied.
    DEFAULT_DENIED = frozenset({"network:listen"})

    def __init__(self, allowed: set[str] | None = None, denied: set[str] | None = None,
                 require_declared: bool = True):
        # Deny-by-default: a tool that needs capabilities (inferred from tags/permission) but
        # declares none is refused. Pass ``require_declared=False`` to opt out.
        self.require_declared = require_declared
        self.allowed = set(allowed) if allowed is not None else None
        self.denied = set(self.DEFAULT_DENIED if denied is None else denied)

    def validate_declared(self, requested: list[str] | set[str], declared: list[str] | set[str]) -> tuple[bool, str]:
        """Deny any capability a tool uses that it did NOT declare (and anything unknown)."""
        undeclared = set(requested) - set(declared)
        if undeclared:
            return False, f"capabilities used but not declared: {sorted(undeclared)}"
        return self.validate(requested)

    def validate_tool(self, declared: list[str] | set[str], inferred: list[str] | set[str]) -> tuple[bool, str]:
        """Validate a tool: it must declare its capabilities when it needs any."""
        if self.require_declared and not declared and inferred:
            return False, f"capabilities needed but not declared: {sorted(inferred)}"
        return self.validate(declared or inferred)

    def validate(self, capabilities: list[str] | set[str]) -> tuple[bool, str]:
        declared = set(capabilities)
        unknown = declared - KNOWN_CAPABILITIES
        if unknown:
            return False, f"unknown capabilities: {sorted(unknown)}"
        blocked = declared & self.denied
        if blocked:
            return False, f"denied capabilities: {sorted(blocked)}"
        if self.allowed is not None:
            missing = declared - self.allowed
            if missing:
                return False, f"capabilities not allowed: {sorted(missing)}"
        return True, ""

    @staticmethod
    def risk(capabilities: list[str] | set[str]) -> str:
        return "high" if set(capabilities) & DANGEROUS_CAPABILITIES else "low"

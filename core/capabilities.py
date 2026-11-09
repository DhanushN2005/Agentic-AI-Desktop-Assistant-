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

    def __init__(self, allowed: set[str] | None = None, denied: set[str] | None = None):
        self.allowed = set(allowed) if allowed is not None else None
        self.denied = set(denied or ())

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

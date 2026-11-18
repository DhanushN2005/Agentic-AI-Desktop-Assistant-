from core.action_result import ActionResult
from core.capabilities import CapabilityPolicy
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSpec


def test_unknown_capability_is_rejected():
    ok, err = CapabilityPolicy().validate(["teleport"])
    assert ok is False
    assert "unknown" in err


def test_denied_shell_capability_blocks_tool_execution():
    executed = []
    registry = ToolRegistry(policy=CapabilityPolicy(denied={"shell:execute"}))
    registry.register(
        ToolSpec(
            name="terminal.run",
            description="Run a command",
            params=[],
            permission=PermissionLevel.USER_CONFIRMATION,
            execute_fn=lambda: executed.append(True) or ActionResult.ok("ran"),
            tags=["terminal"],
        )
    )
    result = registry.execute("terminal.run", {})
    assert result.success is False
    assert "Capability denied" in result.message
    assert executed == []


def test_read_only_tool_still_runs_under_denied_shell_policy():
    registry = ToolRegistry(policy=CapabilityPolicy(denied={"shell:execute"}))
    registry.register(
        ToolSpec(
            name="file.read",
            description="Read",
            params=[],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda: ActionResult.ok("content"),
            tags=["file"],
            capabilities=["filesystem:read"],  # deny-by-default: tools must declare what they need
        )
    )
    result = registry.execute("file.read", {})
    assert result.success is True
    assert result.message == "content"

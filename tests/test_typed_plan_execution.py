"""Planner output must reach the executor as a typed graph (architecture fix: execution path)."""
from types import SimpleNamespace

from core.action_result import ActionResult
from core.agent_executor import AgentExecutor
from core.goal_planner import StepStatus, TaskGraph, TaskStep, VerificationStrategy
from core.permission_system import PermissionSystem
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec


def _executor(handler=None, ran=None):
    ran = ran if ran is not None else []
    reg = ToolRegistry()
    reg.permission_gate = PermissionSystem(default_level=PermissionLevel.SAFE_ACTION)
    reg.register(ToolSpec(
        name="code.search", description="search", params=[ToolSchema("query", "str", True)],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=lambda query: (ran.append(query), ActionResult.ok(message="ok", intent="code.search"))[1],
        timeout=5,
    ))
    orch = SimpleNamespace(handle_command=handler or (lambda *a, **k: "executed"))
    ex = AgentExecutor(reg, reg.permission_gate, orch=orch)
    ex.APPROVAL_WAIT_SECONDS = 0.2
    return ex, ran


def _graph(*steps):
    return TaskGraph(goal_id="g", original_goal="goal", steps=list(steps))


def test_taskstep_has_no_command_attribute_so_callers_must_use_description():
    # Regression: the orchestrator once read step.command and silently discarded every plan.
    s = TaskStep(task_id="1", description="d", tool="")
    assert not hasattr(s, "command") and s.description == "d"


def test_valid_typed_call_uses_registry():
    ex, ran = _executor()
    step = TaskStep(task_id="s", description="find x", tool="code.search", arguments={"query": "x"})
    ex.execute(_graph(step), speak=False)
    assert ran == ["x"] and step.status == StepStatus.COMPLETED


def test_unknown_tool_or_missing_args_fall_back_to_handler():
    calls = []
    ex, ran = _executor(handler=lambda cmd, **k: calls.append((cmd, k)) or "executed")
    unknown = TaskStep(task_id="a", description="open notepad", tool="app.open")
    no_args = TaskStep(task_id="b", description="find stuff", tool="code.search")  # query missing
    ex.execute(_graph(unknown, no_args), speak=False)
    assert [c[0] for c in calls] == ["open notepad", "find stuff"]
    assert all(c[1].get("is_subcommand") for c in calls) and ran == []


def test_handler_deferred_or_blocked_is_not_counted_as_success():
    for status in ("awaiting_confirmation", "blocked", "failed"):
        ex, _ = _executor(handler=lambda cmd, status=status, **k: status)
        step = TaskStep(task_id="s", description="tidy things", tool="", max_retries=0)
        ex.execute(_graph(step), speak=False)
        assert step.status == StepStatus.FAILED, status


def test_handler_steps_are_not_rerun_by_generic_verification():
    calls = []
    ex, _ = _executor(handler=lambda cmd, **k: calls.append(cmd) or "executed")
    step = TaskStep(task_id="s", description="save the file", tool="",
                    verification=VerificationStrategy.FILE_EXISTS)
    ex.execute(_graph(step), speak=False)
    assert calls == ["save the file"] and step.status == StepStatus.COMPLETED


def test_controller_does_not_reprompt_when_approval_already_active(tmp_path, monkeypatch):
    from test_danger_gate import FakeGlobalMemory, FakeOrchestrator

    from core.controller import FlexieController

    monkeypatch.setattr("core.controller.GlobalMemory", FakeGlobalMemory)
    orch = FakeOrchestrator()
    orch.speak = lambda *a, **k: None
    ps = PermissionSystem(default_level=PermissionLevel.SAFE_ACTION)
    orch.permission_system = ps
    ran = []
    ctl = FlexieController(orch, lambda cmd, *a, **k: ran.append(cmd))
    ctl.telemetry.log_path = str(tmp_path / "t.log")

    assert ctl.execute("delete the old report") == "awaiting_confirmation"   # no approval yet
    ctl.pending_confirmation = None
    ps.escalate(PermissionLevel.DANGEROUS, ttl_seconds=30)                    # user approved
    assert ctl.execute("delete the old report") == "executed"
    assert ran == ["delete the old report"]

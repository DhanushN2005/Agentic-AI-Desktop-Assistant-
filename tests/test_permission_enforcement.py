"""Permission enforcement must fail closed (architecture fix #2)."""
from core.action_result import ActionResult
from core.agent_executor import AgentExecutor
from core.goal_planner import StepStatus, TaskGraph, TaskStep
from core.permission_system import PermissionSystem
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec


def _registry(ran):
    reg = ToolRegistry()
    reg.permission_gate = PermissionSystem()  # default level READ_ONLY
    def _do(path: str = "x"):
        ran.append(path)
        return ActionResult.ok(message="done", intent="file.write")
    reg.register(ToolSpec(
        name="file.write", description="write",
        params=[ToolSchema("path", "str", False, "x")],
        permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_do, timeout=5,
        capabilities=["filesystem:write"],
    ))
    return reg


def test_registry_blocks_tool_above_current_level():
    ran = []
    res = _registry(ran).execute("file.write", {"path": "a"})
    assert not res.success and ran == []
    assert res.data.get("permission_denied") is True


def test_registry_allows_after_escalation():
    ran = []
    reg = _registry(ran)
    reg.permission_gate.escalate(PermissionLevel.USER_CONFIRMATION)
    assert reg.execute("file.write", {"path": "a"}).success and ran == ["a"]


def test_agent_executor_does_not_run_denied_step():
    ran = []
    reg = _registry(ran)
    ex = AgentExecutor(reg, reg.permission_gate)
    ex.APPROVAL_WAIT_SECONDS = 0.3
    step = TaskStep(task_id="s1", description="write a file", tool="file.write", arguments={"path": "a"})
    ex.execute(TaskGraph(goal_id="g1", original_goal="g", steps=[step]), speak=False)
    assert ran == []
    assert step.status == StepStatus.FAILED


def test_python_exec_rejects_use_sandbox_argument():
    from core.coding_tools import register_coding_tools

    class _O:  # minimal orchestrator stub
        pass

    reg = ToolRegistry()
    register_coding_tools(reg, _O())
    res = reg.execute("python.exec", {"code": "print(1)", "use_sandbox": False})
    assert not res.success and "Unknown parameters" in res.message


def test_approval_is_consumed_after_step():
    ran = []
    reg = _registry(ran)
    ex = AgentExecutor(reg, reg.permission_gate)
    ex.APPROVAL_WAIT_SECONDS = 2
    import threading
    import time

    def approver():
        for _ in range(40):
            if reg.permission_gate.get_pending_request():
                reg.permission_gate.approve_request()
                return
            time.sleep(0.05)
    threading.Thread(target=approver, daemon=True).start()
    step = TaskStep(task_id="s1", description="write a file", tool="file.write", arguments={"path": "a"})
    ex.execute(TaskGraph(goal_id="g1", original_goal="g", steps=[step]), speak=False)
    assert ran == ["a"]
    assert reg.permission_gate.current_level == PermissionLevel.READ_ONLY  # no lingering escalation


def test_untrusted_content_gates_effectful_tools_until_next_turn():
    from evals.agent_run import build_registry

    reg = build_registry()
    gate = reg.permission_gate
    assert reg.execute("browser_click", {"selector_or_text": "ok"}).success      # clean turn
    assert reg.execute("browser_extract", {}).success                             # untrusted page read
    assert gate.is_tainted
    denied = reg.execute("browser_click", {"selector_or_text": "ok"})
    assert not denied.success and denied.data.get("permission_denied")
    assert reg.execute("browser_search", {"query": "x"}).success                  # plain browsing stays free
    gate.clear_taint()                                                            # new user turn
    assert reg.execute("browser_click", {"selector_or_text": "ok"}).success


def test_new_user_turn_clears_taint_but_subcommands_do_not():
    from core.orchestrator import FlexieOrchestrator

    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    ps = PermissionSystem()
    ps.mark_untrusted("browser_extract")
    o.permission_system = ps
    o.trace_collector = type("T", (), {"start": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop"))})()
    for kwargs, expect_tainted in (({"is_subcommand": True}, True), ({}, False)):
        ps.mark_untrusted("browser_extract")
        try:
            o.handle_command("hello", **kwargs)
        except RuntimeError:
            pass
        assert ps.is_tainted is expect_tainted

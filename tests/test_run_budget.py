"""Run budget + loop guard (agent harness)."""
from types import SimpleNamespace

from core.agent_executor import AgentExecutor
from core.goal_planner import StepStatus, TaskGraph, TaskStep
from core.permission_system import PermissionSystem
from core.run_budget import RunBudget
from core.tool_registry import PermissionLevel, ToolRegistry


def _ex(handler):
    reg = ToolRegistry()
    reg.permission_gate = PermissionSystem(default_level=PermissionLevel.SAFE_ACTION)
    ex = AgentExecutor(reg, reg.permission_gate, orch=SimpleNamespace(handle_command=handler))
    ex.APPROVAL_WAIT_SECONDS = 0.1
    return ex


def _steps(n, same=False):
    return [TaskStep(task_id=f"s{i}", description="open notepad" if same else f"step {i}", tool="",
                     depends_on=[f"s{i-1}"] if i else []) for i in range(n)]


def test_budget_trips_on_step_count():
    b = RunBudget(max_steps=3, max_seconds=999, max_repeats=99)
    assert [b.charge("", {}, f"a{i}") for i in range(3)] == [None, None, None]
    assert "step budget" in b.charge("", {}, "a4")


def test_budget_trips_on_time(monkeypatch):
    b = RunBudget(max_steps=99, max_seconds=-1.0, max_repeats=99)
    assert "time budget" in b.charge("", {}, "x")


def test_budget_trips_on_identical_repeats():
    b = RunBudget(max_steps=99, max_seconds=999, max_repeats=2)
    assert b.charge("file.read", {"path": "a"}, "read") is None
    assert b.charge("file.read", {"path": "a"}, "read") is None
    assert "loop detected" in b.charge("file.read", {"path": "a"}, "read")
    # different args are a different action
    assert RunBudget(max_repeats=1).charge("file.read", {"path": "b"}, "read") is None


def test_executor_stops_a_runaway_plan_and_cancels_the_rest():
    calls = []
    ex = _ex(lambda cmd, **k: calls.append(cmd) or "executed")
    import core.agent_executor as mod
    steps = _steps(40)
    orig = mod.RunBudget
    mod.RunBudget = lambda: orig(max_steps=5, max_seconds=999, max_repeats=99)
    try:
        res = ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=steps), speak=False)
    finally:
        mod.RunBudget = orig
    assert len(calls) == 5
    assert not res.success and "step budget" in res.message
    done = [s.status for s in steps]
    assert done.count(StepStatus.COMPLETED) == 5          # ran exactly the budget
    assert done.count(StepStatus.FAILED) == 1             # the step that hit the limit
    assert done.count(StepStatus.CANCELLED) == 34         # nothing after it ran


def test_distinct_steps_with_identical_text_are_not_a_loop():
    """Five different 'press next' steps are five legitimate actions, not a loop."""
    calls = []
    ex = _ex(lambda cmd, **k: calls.append(cmd) or "executed")
    res = ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=_steps(10, same=True)), speak=False)
    assert len(calls) == 10 and res.success


def test_retries_count_against_the_budget():
    ex = _ex(lambda cmd, **k: "failed")  # always fails -> one retry, then marked failed
    steps = [TaskStep(task_id="s", description="flaky thing", tool="", max_retries=50)]
    res = ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=steps), speak=False)
    assert not res.success
    assert ex.budget.steps_used == 2  # the first attempt AND its retry were both charged


def test_budget_resets_for_each_plan():
    ex = _ex(lambda cmd, **k: "executed")
    for _ in range(3):
        res = ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=_steps(2)), speak=False)
        assert res.success

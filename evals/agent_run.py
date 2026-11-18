"""Agent-level eval harness (deterministic: fake LLM, stubbed tool bodies, no network).

The routing evals only check which intent the regex router picks. These check the
agent *around* the model: plan quality and sanitising, permission enforcement, run
budgets / loop guard, confirmation strictness and memory forgetting.

Usage:
    python -m evals.agent_run
    python -m evals.agent_run --min-pass 1.0
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.action_result import ActionResult
from core.agent_executor import AgentExecutor
from core.danger_gate import DangerGate
from core.goal_planner import GoalPlanner, StepStatus, TaskGraph, TaskStep
from core.permission_system import PermissionSystem
from core.tool_registry import PermissionLevel, ToolRegistry

ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = ROOT / "tasks" / "agent.jsonl"


class _Stub:
    def __getattr__(self, _name):
        return None


def build_registry(ran: list | None = None, level: str = "SAFE_ACTION") -> ToolRegistry:
    """Real tool schemas/permissions; tool bodies replaced by a recorder (no side effects)."""
    from core.coding_tools import register_coding_tools

    ran = ran if ran is not None else []
    reg = ToolRegistry()
    register_coding_tools(reg, _Stub())
    try:
        from core.browser_and_comm_tools import register_browser_and_comm_tools
        register_browser_and_comm_tools(reg, _Stub())
    except Exception as e:  # browser deps are optional in CI
        logging.getLogger("evals").debug("browser tools not registered: %s", e)
    for spec in reg._tools.values():
        def _record(*_a, _name=spec.name, **kw):
            ran.append((_name, kw))
            return ActionResult.ok(message="stub", intent=_name)
        spec.execute_fn = _record
    reg.permission_gate = PermissionSystem(default_level=PermissionLevel[level])
    return reg


class _FakeBrain:
    def __init__(self, response: Any):
        self.response = response

    def ask(self, *_a, **_k):
        return self.response if isinstance(self.response, str) else json.dumps(self.response)


# ----------------------------------------------------------------------------- scenarios
def run_plan(t: dict) -> tuple[bool, str]:
    reg = build_registry()
    planner = GoalPlanner(brain=_FakeBrain(t["llm"]), tool_registry=reg)
    steps = planner.decompose(t["goal"]).steps
    exp = t["expect"]
    if "n_steps" in exp and len(steps) != exp["n_steps"]:
        return False, f"n_steps {len(steps)} != {exp['n_steps']}"
    if "max_steps" in exp and len(steps) > exp["max_steps"]:
        return False, f"{len(steps)} steps > cap {exp['max_steps']}"
    if "tools" in exp and [s.tool for s in steps] != exp["tools"]:
        return False, f"tools {[s.tool for s in steps]} != {exp['tools']}"
    for idx, args in exp.get("args", {}).items():
        if steps[int(idx)].arguments != args:
            return False, f"args[{idx}] {steps[int(idx)].arguments} != {args}"
    if exp.get("timeout_cap") and any(s.timeout > exp["timeout_cap"] for s in steps):
        return False, "timeout not capped"
    return True, ""


def run_permission(t: dict) -> tuple[bool, str]:
    ran: list = []
    reg = build_registry(ran, t.get("level", "SAFE_ACTION"))
    res = reg.execute(t["tool"], t.get("args", {}))
    if bool(ran) != t["expect"]["ran"]:
        return False, f"ran={bool(ran)} expected {t['expect']['ran']} ({res.message})"
    return True, ""


def run_executor_permission(t: dict) -> tuple[bool, str]:
    ran: list = []
    reg = build_registry(ran, t.get("level", "SAFE_ACTION"))
    orch = SimpleNamespace(handle_command=lambda *a, **k: "executed")
    ex = AgentExecutor(reg, reg.permission_gate, orch=orch)
    ex.APPROVAL_WAIT_SECONDS = 0.1
    step = TaskStep(task_id="s", description=t.get("description", "do it"), tool=t["tool"],
                    arguments=t.get("args", {}))
    ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=[step]), speak=False)
    ok = (step.status == StepStatus.COMPLETED) == t["expect"]["completed"]
    return ok, "" if ok else f"status {step.status.name}"


def run_budget(t: dict) -> tuple[bool, str]:
    import core.agent_executor as mod

    calls: list = []
    reg = build_registry()
    orch = SimpleNamespace(handle_command=lambda c, **k: calls.append(c) or "executed")
    ex = AgentExecutor(reg, reg.permission_gate, orch=orch)
    orig = mod.RunBudget
    mod.RunBudget = lambda: orig(max_steps=t.get("max_steps", 20), max_seconds=999,
                                 max_repeats=t.get("max_repeats", 3))
    try:
        steps = [TaskStep(task_id=f"s{i}", description="same thing" if t.get("same") else f"step {i}",
                          tool="", depends_on=[f"s{i-1}"] if i else []) for i in range(t["steps"])]
        res = ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=steps), speak=False)
    finally:
        mod.RunBudget = orig
    exp = t["expect"]
    if len(calls) != exp["ran"]:
        return False, f"ran {len(calls)} != {exp['ran']}"
    if exp.get("tripped") and exp["tripped"] not in (res.message or ""):
        return False, f"message {res.message!r} lacks {exp['tripped']!r}"
    return True, ""


def run_confirm(t: dict) -> tuple[bool, str]:
    got = DangerGate().is_confirmation(t["reply"])
    return got == t["expect"], "" if got == t["expect"] else f"is_confirmation={got}"


def run_forget(t: dict) -> tuple[bool, str]:
    from core.memory_facade import MemoryFacade
    from core.memory_manager import MemoryManager
    from engines.memory_system import MemorySystem
    from engines.self_awareness import SelfAwareness

    tmp = tempfile.mkdtemp()
    mm = MemoryManager.__new__(MemoryManager)
    mm.logger = logging.getLogger("eval")
    mm._entries = {}
    mm.DB_PATH = os.path.join(tmp, "mm.db")
    mm._WIKI_DEBOUNCE_SECONDS = 0
    mm.export_to_markdown = lambda *a, **k: ""
    mm._ensure_db()
    orch = SimpleNamespace(memory_manager=mm, memory_system=MemorySystem(os.path.join(tmp, "ms.db")),
                           awareness=SelfAwareness(os.path.join(tmp, "aw.db")), memory=None, brain=None)
    facade = MemoryFacade(orch)
    facade.remember_fact(t["key"], t["value"], raw_fact=t["fact"])
    facade.forget(t["forget"])
    leftover = bool(mm.search(t["forget"])) or bool(orch.awareness.recall_facts())
    ok = (not leftover) == t["expect"]["gone"]
    return ok, "" if ok else "fact survived in a store"


def run_specialist(t: dict) -> tuple[bool, str]:
    from core.specialists import AgentTeam, SpecialistRole

    ran: list = []
    team = AgentTeam(tool_registry=build_registry(ran))
    agent = team._by_role[SpecialistRole(t["role"])]
    script = list(t["script"])
    agent.generate = lambda messages, tools=None: script.pop(0) if script else {"content": "done", "tool_calls": []}
    agent.max_turns = t.get("max_turns", agent.max_turns)
    out = agent.run(t["task"])
    exp = t["expect"]
    names = [n for n, _ in ran]
    if "ran" in exp and names != exp["ran"]:
        return False, f"tools run {names} != {exp['ran']}"
    if "max_ran" in exp and len(names) > exp["max_ran"]:
        return False, f"{len(names)} tool runs > cap {exp['max_ran']}"
    if exp.get("out_contains") and exp["out_contains"] not in out:
        return False, f"output {out!r} lacks {exp['out_contains']!r}"
    return True, ""


def run_route(t: dict) -> tuple[bool, str]:
    from core.specialists import AgentTeam

    got = AgentTeam().route_task(t["goal"]).role.value
    return got == t["expect"], "" if got == t["expect"] else f"routed to {got}"


def run_taint(t: dict) -> tuple[bool, str]:
    """Calls run in order against one registry; 'new_turn' entries clear taint like a new user turn."""
    ran: list = []
    reg = build_registry(ran)
    outcomes = []
    for call in t["calls"]:
        if call.get("new_turn"):
            reg.permission_gate.clear_taint()
            continue
        before = len(ran)
        reg.execute(call["tool"], call.get("args", {}))
        outcomes.append(len(ran) > before)
    ok = outcomes == t["expect"]["executed"]
    return ok, "" if ok else f"executed {outcomes} != {t['expect']['executed']}"


def run_usage(t: dict) -> tuple[bool, str]:
    """Replay LLM calls through the usage tracker; check tokens, cost and attribution."""
    from types import SimpleNamespace as NS

    from core.telemetry.usage import UsageTracker, begin_command, end_command, set_tracker, track_llm

    tracker = UsageTracker(persist=False)
    previous = set_tracker(tracker)
    try:
        token = begin_command("eval-cmd")
        for c in t["calls"]:
            with track_llm(c["provider"], c.get("model", "m"), prompt_text="p" * c.get("prompt_chars", 0)) as call:
                u = c.get("usage")
                call.done("c" * c.get("completion_chars", 0), NS(**u) if u else None)
        end_command(token)
        cu = tracker.command("eval-cmd")
        exp = t["expect"]
        if cu.total_tokens != exp["tokens"]:
            return False, f"tokens {cu.total_tokens} != {exp['tokens']}"
        if "estimated_calls" in exp and cu.estimated_calls != exp["estimated_calls"]:
            return False, f"estimated_calls {cu.estimated_calls} != {exp['estimated_calls']}"
        if "costly" in exp and (cu.cost_usd > 0) != exp["costly"]:
            return False, f"cost {cu.cost_usd} (costly expected {exp['costly']})"
        return True, ""
    finally:
        set_tracker(previous)


RUNNERS = {
    "plan": run_plan, "permission": run_permission, "executor_permission": run_executor_permission,
    "budget": run_budget, "confirm": run_confirm, "forget": run_forget,
    "specialist": run_specialist, "route": run_route, "taint": run_taint, "usage": run_usage,
}


@dataclass
class Result:
    task_id: str
    kind: str
    passed: bool
    detail: str
    latency_ms: float


def load_tasks(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(json.loads(line))
    return out


def run(tasks: list[dict[str, Any]]) -> list[Result]:
    results = []
    for i, t in enumerate(tasks, 1):
        start = time.perf_counter()
        try:
            ok, detail = RUNNERS[t["kind"]](t)
        except Exception as e:  # a crashing scenario is a failed scenario, never a skipped one
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append(Result(t.get("task_id", f"agent-{i:03d}"), t["kind"], ok, detail,
                              (time.perf_counter() - start) * 1000))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run Flexie agent-level evals")
    ap.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--min-pass", type=float, default=1.0)
    args = ap.parse_args(argv)

    results = run(load_tasks(args.tasks))
    passed = sum(r.passed for r in results)
    rate = passed / len(results) if results else 0.0
    out = args.output or (ROOT / "results" / f"agent-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(asdict(r)) + "\n" for r in results), encoding="utf-8")

    for r in results:
        if not r.passed:
            print(f"  FAIL {r.task_id} [{r.kind}]: {r.detail}")
    by_kind: dict[str, list[bool]] = {}
    for r in results:
        by_kind.setdefault(r.kind, []).append(r.passed)
    print("agent: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(by_kind.items())))
    print(f"agent: {passed}/{len(results)} passed ({rate:.1%})")
    return 0 if rate >= args.min_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())

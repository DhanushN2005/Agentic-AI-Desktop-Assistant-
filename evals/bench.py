"""Flexie benchmark: speed of the deterministic agent stack + quality gates.

Measures everything that does NOT need an LLM or network, so numbers are stable and
reproducible: routing, permission/registry overhead, the tool loop, plan sanitising,
plan execution, memory remember/forget, budget accounting, and import (startup) cost.
It does not measure model quality or end-to-end task success with a real model.

Usage:
    python -m evals.bench                 # writes evals/results/bench-<ts>.json + .md
    python -m evals.bench --quick         # fewer iterations
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
logging.disable(logging.CRITICAL)


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def timeit(fn: Callable[[], Any], n: int, warmup: int = 5) -> dict[str, float]:
    """Per-call latency stats in microseconds."""
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1e6)
    total_s = sum(samples) / 1e6
    return {
        "n": n,
        "p50_us": round(_pct(samples, 0.50), 1),
        "p95_us": round(_pct(samples, 0.95), 1),
        "p99_us": round(_pct(samples, 0.99), 1),
        "mean_us": round(statistics.fmean(samples), 1),
        "ops_per_sec": round(n / total_s, 1) if total_s else 0.0,
    }


# ---------------------------------------------------------------------------- benches
def bench_routing(n: int) -> dict:
    from core.router import IntentRouter
    from evals.run import load_tasks

    router = IntentRouter()
    queries = [t["query"] for t in load_tasks(ROOT / "tasks" / "routing.jsonl")]
    i = [0]

    def one():
        router.route(queries[i[0] % len(queries)])
        i[0] += 1

    return timeit(one, n)


def _registry(ran: list):
    from evals.agent_run import build_registry

    return build_registry(ran)


def bench_permission_check(n: int) -> dict:
    reg = _registry([])
    tool = reg.get("file.read")
    return timeit(lambda: reg.permission_gate.check_permission(tool), n)


def bench_registry_execute(n: int) -> dict:
    ran: list = []
    reg = _registry(ran)

    def one():
        reg.execute("file.read", {"path": "a.txt"})
        ran.clear()

    return timeit(one, n)


def bench_scoped_execute(n: int) -> dict:
    from core.agents import ScopedToolRegistry

    ran: list = []
    scoped = ScopedToolRegistry(_registry(ran), {"file.read", "code.search"})

    def one():
        scoped.execute("file.read", {"path": "a.txt"})
        ran.clear()

    return timeit(one, n)


def bench_budget(n: int) -> dict:
    from core.run_budget import RunBudget

    b = RunBudget(max_steps=10**9, max_seconds=10**9, max_repeats=10**9)
    i = [0]

    def one():
        b.charge("file.read", {"path": f"f{i[0] % 50}"}, "")
        i[0] += 1

    return timeit(one, n)


def bench_agent_loop(n: int) -> dict:
    """Full ToolUsingAgent run: 3 tool calls + final answer, fake LLM, stub tools."""
    from core.agents import ScopedToolRegistry, ToolUsingAgent

    ran: list = []
    scoped = ScopedToolRegistry(_registry(ran), {"file.read", "code.search", "git.status"})

    def make_gen():
        script = [
            {"content": "", "tool_calls": [{"id": "1", "function": {"name": "code.search", "arguments": {"query": "x"}}}]},
            {"content": "", "tool_calls": [{"id": "2", "function": {"name": "file.read", "arguments": {"path": "a"}}}]},
            {"content": "", "tool_calls": [{"id": "3", "function": {"name": "git.status", "arguments": {}}}]},
            {"content": "done", "tool_calls": []},
        ]
        return lambda messages, tools=None: script.pop(0)

    def one():
        ToolUsingAgent("bench", make_gen(), scoped, max_turns=6).run("task")
        ran.clear()

    return timeit(one, n)


def bench_plan_sanitise(n: int) -> dict:
    from core.goal_planner import GoalPlanner

    steps = [{"description": f"step {i}", "tool": "file.read" if i % 2 else "ghost.tool",
              "arguments": {"path": "a"}, "timeout": 99999} for i in range(12)]
    steps.insert(3, "junk")
    brain = SimpleNamespace(ask=lambda *a, **k: json.dumps(steps))
    planner = GoalPlanner(brain=brain, tool_registry=_registry([]))
    return timeit(lambda: planner.decompose("do many things and then more"), n)


def bench_plan_execution(n: int) -> dict:
    """AgentExecutor over a 5-step handler plan (fake handler)."""
    from core.agent_executor import AgentExecutor
    from core.goal_planner import TaskGraph, TaskStep

    reg = _registry([])
    ex = AgentExecutor(reg, reg.permission_gate, orch=SimpleNamespace(handle_command=lambda *a, **k: "executed"))

    def one():
        steps = [TaskStep(task_id=f"s{i}", description=f"step {i}", tool="",
                          depends_on=[f"s{i-1}"] if i else []) for i in range(5)]
        ex.execute(TaskGraph(goal_id="g", original_goal="g", steps=steps), speak=False)

    return timeit(one, n, warmup=2)


def bench_memory(n: int) -> dict:
    from core.memory_facade import MemoryFacade
    from core.memory_manager import MemoryManager
    from engines.memory_system import MemorySystem
    from engines.self_awareness import SelfAwareness

    tmp = tempfile.mkdtemp()
    mm = MemoryManager.__new__(MemoryManager)
    mm.logger = logging.getLogger("bench")
    mm._entries = {}
    mm.DB_PATH = os.path.join(tmp, "mm.db")
    mm._WIKI_DEBOUNCE_SECONDS = 0
    mm.export_to_markdown = lambda *a, **k: ""
    mm._ensure_db()
    orch = SimpleNamespace(memory_manager=mm, memory_system=MemorySystem(os.path.join(tmp, "ms.db")),
                           awareness=SelfAwareness(os.path.join(tmp, "aw.db")), memory=None, brain=None)
    facade = MemoryFacade(orch)
    i = [0]

    def remember():
        i[0] += 1
        facade.remember_fact(f"k{i[0]}", f"v{i[0]}", raw_fact=f"fact number {i[0]}")

    def forget():
        facade.forget(f"fact number {max(1, i[0] - 5)}")

    return {"remember_fact": timeit(remember, n), "forget": timeit(forget, n)}


def bench_usage_tracking(n: int) -> dict:
    """Cost of recording one LLM call (in memory), and with SQLite persistence."""
    from types import SimpleNamespace as NS

    from core.telemetry.usage import UsageTracker, begin_command, set_tracker, track_llm

    usage = NS(prompt_tokens=100, completion_tokens=20)

    def one():
        with track_llm("openai", "gpt-4o-mini", prompt_text="hello world") as c:
            c.done("answer", usage)

    prev = set_tracker(UsageTracker(persist=False))
    begin_command("bench")
    try:
        mem = timeit(one, n)
        set_tracker(UsageTracker(persist=True, db_path=os.path.join(tempfile.mkdtemp(), "t.db")))
        persisted = timeit(one, max(20, n // 10))
    finally:
        set_tracker(prev)
    return {"memory": mem, "persisted": persisted}


def bench_imports() -> dict:
    """Cold import cost per module, each in a fresh interpreter."""
    out = {}
    for mod in ("core.router", "core.agent_executor", "core.specialists", "core.goal_planner"):
        code = f"import time;t=time.perf_counter();import {mod};print(round((time.perf_counter()-t)*1000,1))"
        try:
            r = subprocess.run([sys.executable, "-c", code], cwd=PROJECT, capture_output=True, text=True, timeout=60)
            out[mod] = float(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
        except Exception:
            out[mod] = None
    return out


def quality_gates() -> dict:
    from core.router import IntentRouter
    from evals import agent_run
    from evals.run import load_tasks, run_routing, summarize

    routing = summarize(run_routing(IntentRouter(), load_tasks(ROOT / "tasks" / "routing.jsonl")))
    agent = agent_run.run(agent_run.load_tasks(agent_run.DEFAULT_TASKS))
    by_kind: dict[str, list[bool]] = {}
    for r in agent:
        by_kind.setdefault(r.kind, []).append(r.passed)
    return {
        "routing": {"correct": routing["correct"], "total": routing["total"],
                    "accuracy": round(routing["accuracy"], 4)},
        "agent": {"passed": sum(r.passed for r in agent), "total": len(agent),
                  "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_kind.items())}},
    }


def repo_stats() -> dict:
    py = [p for p in PROJECT.rglob("*.py") if ".git" not in p.parts and "__pycache__" not in p.parts]
    src = [p for p in py if "tests" not in p.parts]

    def loc(files):
        return sum(len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) for p in files)

    try:
        collected = subprocess.run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
                                   cwd=PROJECT, capture_output=True, text=True, timeout=120).stdout
        tests = next((int(ln.split()[0]) for ln in collected.splitlines() if "tests collected" in ln or "test collected" in ln), None)
    except Exception:
        tests = None
    big = sorted(((len(p.read_text(encoding="utf-8", errors="ignore").splitlines()), str(p.relative_to(PROJECT))) for p in src),
                 reverse=True)[:3]
    return {"source_loc": loc(src), "test_loc": loc([p for p in py if "tests" in p.parts]),
            "tests_collected": tests, "largest_files": [{"loc": n, "file": f} for n, f in big]}


# ------------------------------------------------------------------------------ report
def render_markdown(r: dict) -> str:
    m = r["machine"]
    L = ["# Flexie benchmark report", "",
         f"- Date: {r['timestamp']}",
         f"- Machine: {m['platform']} · Python {m['python']} · {m['cpus']} CPUs",
         "- Scope: deterministic agent stack only (no LLM, no network). Fake model + stub tool bodies.", "",
         "## Quality gates", ""]
    q = r["quality"]
    L += [f"- Routing eval: **{q['routing']['correct']}/{q['routing']['total']}** ({q['routing']['accuracy']:.1%})",
          f"- Agent evals: **{q['agent']['passed']}/{q['agent']['total']}** — " +
          ", ".join(f"{k} {v}" for k, v in q['agent']['by_kind'].items()), "",
          "## Latency (per call, microseconds)", "",
          "| Component | n | p50 | p95 | p99 | ops/sec |", "|---|---:|---:|---:|---:|---:|"]
    names = {
        "routing": "Intent routing (regex tier)", "permission_check": "Permission check",
        "registry_execute": "Registry execute (gated, stub tool)", "scoped_execute": "Scoped registry execute",
        "budget_charge": "Run budget charge", "agent_loop": "Tool loop: 3 tool calls + answer",
        "plan_sanitise": "Plan decompose + sanitise (12 steps)", "plan_execution": "Plan execution (5 handler steps)",
        "memory_remember": "Memory: remember fact (4 stores)", "memory_forget": "Memory: forget (all stores)",
        "usage_track_memory": "Usage tracking per LLM call (in memory)",
        "usage_track_persisted": "Usage tracking per LLM call (+ SQLite row)",
    }
    for key, label in names.items():
        s = r["latency"][key]
        L.append(f"| {label} | {s['n']} | {s['p50_us']:.0f} | {s['p95_us']:.0f} | {s['p99_us']:.0f} | {s['ops_per_sec']:.0f} |")
    L += ["", "## Cold import time (ms, fresh interpreter)", ""]
    L += [f"- `{k}`: {v if v is not None else 'failed'}" for k, v in r["imports_ms"].items()]
    s = r["repo"]
    L += ["", "## Repository", "",
          f"- Source: {s['source_loc']:,} lines · Tests: {s['test_loc']:,} lines · Collected tests: {s['tests_collected']}",
          "- Largest files: " + ", ".join(f"{x['file']} ({x['loc']})" for x in s["largest_files"]), "",
          "## Not measured", "",
          "- Real-model plan quality, tool-selection accuracy or task success.",
          "- Real tokens / dollar cost per command (the telemetry exists, core/telemetry; this benchmark uses a fake model, so only its per-call overhead is measured) and energy per command.",
          "- Voice, desktop and browser automation latency. (Orchestrator startup was timed separately: import + construct ~14.5 s -> ~1.9 s after lazy imports; not part of this script.)",
          "- Any comparison against other agent frameworks."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the Flexie benchmark")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = ap.parse_args(argv)
    scale = 0.2 if args.quick else 1.0
    n = lambda base: max(20, int(base * scale))  # noqa: E731

    sys.path.insert(0, str(PROJECT))
    mem = bench_memory(n(150))
    usage_bench = bench_usage_tracking(n(20000))
    result = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "cpus": os.cpu_count()},
        "latency": {
            "routing": bench_routing(n(3000)),
            "permission_check": bench_permission_check(n(20000)),
            "registry_execute": bench_registry_execute(n(10000)),
            "scoped_execute": bench_scoped_execute(n(10000)),
            "budget_charge": bench_budget(n(50000)),
            "agent_loop": bench_agent_loop(n(2000)),
            "plan_sanitise": bench_plan_sanitise(n(1000)),
            "plan_execution": bench_plan_execution(n(500)),
            "memory_remember": mem["remember_fact"],
            "memory_forget": mem["forget"],
            "usage_track_memory": usage_bench["memory"],
            "usage_track_persisted": usage_bench["persisted"],
        },
        "imports_ms": bench_imports(),
        "quality": quality_gates(),
        "repo": repo_stats(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (args.output_dir / f"bench-{stamp}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    md = render_markdown(result)
    (args.output_dir / f"bench-{stamp}.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

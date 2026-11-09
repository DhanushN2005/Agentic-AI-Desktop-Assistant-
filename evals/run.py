"""Flexie evaluation harness.

Usage:
    python -m evals.run
    python -m evals.run --suite routing --min-accuracy 0.95
    python -m evals.run --tasks evals/tasks/routing.jsonl --output results.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.router import IntentRouter

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"


@dataclass
class Result:
    task_id: str
    query: str
    expected: str
    predicted: str
    confidence: float
    correct: bool
    latency_ms: float


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                tasks.append(json.loads(line))
    return tasks


def run_routing(router: IntentRouter, tasks: list[dict[str, Any]]) -> list[Result]:
    results = []
    for index, task in enumerate(tasks, start=1):
        query = task["query"]
        started = time.perf_counter()
        predicted, confidence = router.route(query)
        latency_ms = (time.perf_counter() - started) * 1000
        results.append(
            Result(
                task_id=task.get("task_id", f"route-{index:03d}"),
                query=query,
                expected=task["expected"],
                predicted=predicted,
                confidence=confidence,
                correct=predicted == task["expected"],
                latency_ms=latency_ms,
            )
        )
    return results


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def summarize(results: list[Result]) -> dict[str, Any]:
    total = len(results)
    correct = sum(1 for result in results if result.correct)
    latencies = [result.latency_ms for result in results]
    return {
        "total": total,
        "correct": correct,
        "accuracy": (correct / total) if total else 0.0,
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


def write_results(results: list[Result], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(asdict(result)) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Flexie evaluations")
    parser.add_argument("--suite", default="routing", choices=["routing"])
    parser.add_argument("--tasks", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-accuracy", type=float, default=0.0)
    args = parser.parse_args(argv)

    tasks_path = args.tasks or (TASKS_DIR / f"{args.suite}.jsonl")
    tasks = load_tasks(tasks_path)
    results = run_routing(IntentRouter(), tasks)
    summary = summarize(results)

    output = args.output or (
        ROOT / "results" / f"{args.suite}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    )
    write_results(results, output)

    failures = [result for result in results if not result.correct]
    if failures:
        print("Failures:")
        for result in failures[:10]:
            print(f"  {result.query!r}: expected {result.expected!r}, got {result.predicted!r}")

    print(
        f"{args.suite}: {summary['correct']}/{summary['total']} correct "
        f"({summary['accuracy']:.1%}), "
        f"p50 {summary['latency_p50_ms']:.2f} ms, "
        f"p95 {summary['latency_p95_ms']:.2f} ms"
    )
    print(f"Results written to {output}")

    return 0 if summary["accuracy"] >= args.min_accuracy else 1


if __name__ == "__main__":
    raise SystemExit(main())

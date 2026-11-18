"""Print token / cost / latency telemetry from the persisted store.

    python -m core.telemetry.report                 # all time
    python -m core.telemetry.report --since-hours 24
    python -m core.telemetry.report --json
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from core.telemetry.store import TelemetryStore


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


def build_report(store: TelemetryStore, since: float | None = None, top: int = 5) -> dict[str, Any]:
    rows = store.export_records(since=since)
    latencies = [r["latency_seconds"] or 0.0 for r in rows]
    estimated = sum(1 for r in rows if r["metadata"].get("estimated"))
    base = store.summary(since=since)
    return {
        "calls": base["total_calls"],
        "estimated_token_calls": estimated,
        "tokens": base["total_tokens"],
        "prompt_tokens": sum((r["prompt_tokens"] or 0) for r in rows),
        "completion_tokens": sum((r["completion_tokens"] or 0) for r in rows),
        "cost_usd": round(base["total_cost"], 6),
        "latency_p50_s": round(_pct(latencies, 0.5), 3),
        "latency_p95_s": round(_pct(latencies, 0.95), 3),
        "per_model": base["per_model"],
        "per_engine": base["per_engine"],
        "top_commands_by_cost": store.top_commands(top, by="cost_usd"),
        "top_commands_by_tokens": store.top_commands(top, by="tokens"),
    }


def render(report: dict[str, Any]) -> str:
    L = ["Flexie LLM usage", "================",
         f"Calls: {report['calls']}  (token counts estimated for {report['estimated_token_calls']})",
         f"Tokens: {report['tokens']:,}  (prompt {report['prompt_tokens']:,} / completion {report['completion_tokens']:,})",
         f"Estimated cost: ${report['cost_usd']:.4f}",
         f"Model-call latency: p50 {report['latency_p50_s']}s  p95 {report['latency_p95_s']}s", "",
         "By engine:"]
    for name, s in sorted(report["per_engine"].items(), key=lambda kv: -kv[1]["cost"]):
        L.append(f"  {name:<12} {s['calls']:>5} calls  {s['tokens']:>9,} tokens  ${s['cost']:.4f}")
    L.append("By model:")
    for name, s in sorted(report["per_model"].items(), key=lambda kv: -kv[1]["tokens"]):
        L.append(f"  {name:<28} {s['calls']:>5} calls  {s['tokens']:>9,} tokens  ${s['cost']:.4f}")
    L.append("Costliest commands:")
    for c in report["top_commands_by_cost"] or []:
        L.append(f"  {c['command_id']}  {c['calls']} calls  {c['tokens'] or 0:,} tokens  ${c['cost_usd'] or 0:.5f}")
    L += ["", "Cost is an estimate (core/telemetry/pricing.py; set FLEXIE_PRICING_FILE for your plan's prices)."]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flexie LLM usage report")
    ap.add_argument("--since-hours", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=None, help="telemetry database path")
    args = ap.parse_args(argv)
    since = time.time() - args.since_hours * 3600 if args.since_hours else None
    report = build_report(TelemetryStore(args.db), since=since)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

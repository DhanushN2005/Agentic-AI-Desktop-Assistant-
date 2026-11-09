"""Read-only aggregation over stored traces."""
from __future__ import annotations

from collections import Counter

from core.traces.store import TraceStore


class TraceAnalyzer:
    def __init__(self, store: TraceStore):
        self.store = store

    def summary(self, limit: int = 1000) -> dict:
        traces = self.store.list_traces(limit=limit)
        steps = [step for trace in traces for step in trace.steps]
        completed = [trace for trace in traces if trace.outcome in ("success", "failure")]
        success = [trace for trace in completed if trace.outcome == "success"]
        return {
            "total_traces": len(traces),
            "total_steps": len(steps),
            "avg_steps_per_trace": (len(steps) / len(traces)) if traces else 0.0,
            "avg_latency": (
                sum(trace.total_latency_seconds for trace in traces) / len(traces)
                if traces
                else 0.0
            ),
            "success_rate": (len(success) / len(completed)) if completed else 0.0,
            "step_type_distribution": dict(Counter(step.step_type.value for step in steps)),
        }

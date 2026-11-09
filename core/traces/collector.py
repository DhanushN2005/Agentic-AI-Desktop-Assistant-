"""Collect complete interaction traces and persist them."""
from __future__ import annotations

import time
from typing import Any

from core.traces.store import TraceStore
from core.traces.trace import StepType, Trace, TraceStep


class TraceCollector:
    """Records a trace explicitly, or from EventBus events on a subscribed bus."""

    def __init__(self, store: TraceStore | None = None):
        self.store = store or TraceStore()
        self._active: dict[str, Trace] = {}

    def start(
        self,
        query: str,
        agent: str = "",
        model: str = "",
        engine: str = "",
    ) -> Trace:
        trace = Trace(query=query, agent=agent, model=model, engine=engine)
        self._active[trace.trace_id] = trace
        return trace

    def step(
        self,
        trace: Trace,
        step_type: StepType | str,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        duration_seconds: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> TraceStep:
        step = TraceStep(
            step_type=StepType(step_type),
            duration_seconds=duration_seconds,
            input=input or {},
            output=output or {},
            metadata=metadata or {},
        )
        trace.add_step(step)
        return step

    def finish(self, trace: Trace, result: str = "", outcome: str | None = None) -> Trace:
        trace.finish(result=result, outcome=outcome)
        self.store.save(trace)
        self._active.pop(trace.trace_id, None)
        return trace

    def subscribe(self, bus: Any) -> None:
        """Attach to an EventBus and record steps for the most recent trace."""
        bus.subscribe("INFERENCE_START", self._on_inference_start)
        bus.subscribe("INFERENCE_END", self._on_inference_end)
        bus.subscribe("TOOL_CALL_START", self._on_tool_start)
        bus.subscribe("TOOL_CALL_END", self._on_tool_end)
        bus.subscribe("MEMORY_RETRIEVE", self._on_memory)
        bus.subscribe("TRACE_COMPLETE", self._on_trace_complete)

    def _current(self) -> Trace | None:
        return next(reversed(self._active.values()), None) if self._active else None

    def _on_inference_start(self, event: Any) -> None:
        trace = self._current()
        if trace:
            trace.metadata["_inference_started"] = time.time()

    def _on_inference_end(self, event: Any) -> None:
        trace = self._current()
        if not trace:
            return
        started = trace.metadata.pop("_inference_started", None)
        duration = time.time() - started if started else 0.0
        payload = getattr(event, "payload", {}) or {}
        self.step(trace, StepType.GENERATE, input=payload, duration_seconds=duration)

    def _on_tool_start(self, event: Any) -> None:
        trace = self._current()
        if trace:
            trace.metadata["_tool_started"] = time.time()

    def _on_tool_end(self, event: Any) -> None:
        trace = self._current()
        if not trace:
            return
        started = trace.metadata.pop("_tool_started", None)
        duration = time.time() - started if started else 0.0
        payload = getattr(event, "payload", {}) or {}
        self.step(trace, StepType.TOOL_CALL, output=payload, duration_seconds=duration)

    def _on_memory(self, event: Any) -> None:
        trace = self._current()
        if trace:
            self.step(trace, StepType.RETRIEVE, input=getattr(event, "payload", {}) or {})

    def _on_trace_complete(self, event: Any) -> None:
        trace = self._current()
        if trace:
            payload = getattr(event, "payload", {}) or {}
            self.finish(
                trace,
                result=payload.get("result", ""),
                outcome=payload.get("outcome"),
            )

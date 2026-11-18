"""Collect complete interaction traces and persist them."""
from __future__ import annotations

import threading
import time
from typing import Any

from core.traces.store import TraceStore
from core.traces.trace import StepType, Trace, TraceStep


class TraceCollector:
    """Records a trace explicitly, or from EventBus events on a subscribed bus."""

    ACTIVE_TTL_SECONDS = 600.0  # traces that never finish are persisted as "abandoned" after this

    def __init__(self, store: TraceStore | None = None, active_ttl: float | None = None):
        self.store = store or TraceStore()
        self._active: dict[str, Trace] = {}
        self._lock = threading.RLock()
        self._active_ttl = self.ACTIVE_TTL_SECONDS if active_ttl is None else active_ttl

    def start(
        self,
        query: str,
        agent: str = "",
        model: str = "",
        engine: str = "",
    ) -> Trace:
        self.reap()
        trace = Trace(query=query, agent=agent, model=model, engine=engine)
        with self._lock:
            self._active[trace.trace_id] = trace
        try:  # events published from this context carry the trace id
            from core.event_bus.bus import current_trace_id
            current_trace_id.set(trace.trace_id)
        except Exception:  # noqa: S110 - tracing must not break the caller
            pass
        return trace

    def reap(self, now: float | None = None) -> int:
        """Persist and drop traces that never finished (older than the TTL)."""
        now = time.time() if now is None else now
        with self._lock:
            stale = [t for t in self._active.values() if now - t.started_at > self._active_ttl]
            for t in stale:
                self._active.pop(t.trace_id, None)
        for t in stale:
            try:
                t.finish(result=t.result, outcome="abandoned")
                self.store.save(t)
            except Exception:  # noqa: S110
                pass
        return len(stale)

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
        with self._lock:
            self._active.pop(trace.trace_id, None)
        try:
            from core.event_bus.bus import current_trace_id
            if current_trace_id.get() == trace.trace_id:
                current_trace_id.set(None)
        except Exception:  # noqa: S110
            pass
        return trace

    def subscribe(self, bus: Any) -> None:
        """Attach to an EventBus and record steps for the most recent trace."""
        bus.subscribe("INFERENCE_START", self._on_inference_start)
        bus.subscribe("INFERENCE_END", self._on_inference_end)
        bus.subscribe("TOOL_CALL_START", self._on_tool_start)
        bus.subscribe("TOOL_CALL_END", self._on_tool_end)
        bus.subscribe("MEMORY_RETRIEVE", self._on_memory)
        bus.subscribe("TRACE_COMPLETE", self._on_trace_complete)

    def _current(self, event: Any = None) -> Trace | None:
        """The trace an event belongs to: by id (payload / captured context), else the only active one.

        With several traces in flight and no id the event is dropped rather than guessed.
        """
        payload = getattr(event, "payload", None) or {}
        tid = payload.get("trace_id") or getattr(event, "trace_id", None)
        with self._lock:
            if tid:
                return self._active.get(tid)
            if len(self._active) == 1:
                return next(iter(self._active.values()))
        return None

    def _on_inference_start(self, event: Any) -> None:
        trace = self._current(event)
        if trace:
            trace.metadata["_inference_started"] = time.time()

    def _on_inference_end(self, event: Any) -> None:
        trace = self._current(event)
        if not trace:
            return
        started = trace.metadata.pop("_inference_started", None)
        duration = time.time() - started if started else 0.0
        payload = getattr(event, "payload", {}) or {}
        self.step(trace, StepType.GENERATE, input=payload, duration_seconds=duration)

    def _on_tool_start(self, event: Any) -> None:
        trace = self._current(event)
        if trace:
            trace.metadata["_tool_started"] = time.time()

    def _on_tool_end(self, event: Any) -> None:
        trace = self._current(event)
        if not trace:
            return
        started = trace.metadata.pop("_tool_started", None)
        duration = time.time() - started if started else 0.0
        payload = getattr(event, "payload", {}) or {}
        self.step(trace, StepType.TOOL_CALL, output=payload, duration_seconds=duration)

    def _on_memory(self, event: Any) -> None:
        trace = self._current(event)
        if trace:
            self.step(trace, StepType.RETRIEVE, input=getattr(event, "payload", {}) or {})

    def _on_trace_complete(self, event: Any) -> None:
        trace = self._current(event)
        if trace:
            payload = getattr(event, "payload", {}) or {}
            self.finish(
                trace,
                result=payload.get("result", ""),
                outcome=payload.get("outcome"),
            )

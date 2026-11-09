from types import SimpleNamespace

from core.traces import StepType, TraceAnalyzer, TraceCollector, TraceStore


def test_trace_roundtrip(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    collector = TraceCollector(store)
    try:
        trace = collector.start("open chrome", agent="orchestrator", model="qwen")
        collector.step(trace, StepType.ROUTE, output={"intent": "app_op"}, duration_seconds=0.01)
        collector.step(trace, StepType.RESPOND, output={"content": "Opened."}, duration_seconds=0.02)
        collector.finish(trace, result="Opened.", outcome="success")

        loaded = store.get(trace.trace_id)
        assert loaded is not None
        assert loaded.query == "open chrome"
        assert [step.step_type for step in loaded.steps] == [StepType.ROUTE, StepType.RESPOND]
        assert loaded.outcome == "success"

        summary = TraceAnalyzer(store).summary()
        assert summary["total_traces"] == 1
        assert summary["success_rate"] == 1.0
        assert summary["step_type_distribution"]["route"] == 1
    finally:
        store.close()


class FakeBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, name, callback):
        self.subscribers.setdefault(name, []).append(callback)

    def publish(self, name, payload):
        for callback in self.subscribers.get(name, []):
            callback(SimpleNamespace(payload=payload))


def test_collector_records_event_bus_steps(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    collector = TraceCollector(store)
    try:
        bus = FakeBus()
        collector.subscribe(bus)
        trace = collector.start("research", agent="researcher", model="local")
        bus.publish("INFERENCE_END", {"model": "local"})
        bus.publish("TOOL_CALL_END", {"tool": "web_search"})
        bus.publish("TRACE_COMPLETE", {"result": "done", "outcome": "success"})

        loaded = store.get(trace.trace_id)
        assert loaded is not None
        assert loaded.outcome == "success"
        assert [step.step_type.value for step in loaded.steps] == ["generate", "tool_call"]
    finally:
        store.close()

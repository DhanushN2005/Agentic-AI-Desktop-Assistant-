from core.telemetry import Telemetry
from core.event_bus.bus import EventBus, Event

class LegacyTelemetryAdapter:
    """Links telemetry logger metrics directly into the new async observability layer."""
    def __init__(self, telemetry: Telemetry):
        self.telemetry = telemetry
        self.bus = EventBus()

    def start_trace(self, command: str) -> dict:
        trace = self.telemetry.start_trace(command)
        self.bus.publish(Event("telemetry.trace.start", {"command": command, "timestamp": trace.get("timestamp")}))
        return trace

    def end_trace(self, trace: dict, status: str = "success", error: str = None) -> dict:
        entry = self.telemetry.end_trace(trace, status, error)
        self.bus.publish(Event("telemetry.trace.end", {
            "cmd": entry["cmd"],
            "latency_ms": entry["latency_ms"],
            "status": entry["status"],
            "error": entry["error"]
        }))
        return entry

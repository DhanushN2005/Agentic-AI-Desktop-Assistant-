import json

from core.telemetry import Telemetry


def test_start_trace_returns_trace():
    telemetry = Telemetry()
    trace = telemetry.start_trace("open chrome")
    assert trace["command"] == "open chrome"
    assert "start_time" in trace
    assert "timestamp" in trace


def test_end_trace_writes_structured_log(tmp_path):
    telemetry = Telemetry()
    telemetry.log_path = str(tmp_path / "telemetry.log")

    trace = telemetry.start_trace("open chrome")
    entry = telemetry.end_trace(trace, status="success")

    assert entry["cmd"] == "open chrome"
    assert entry["status"] == "success"
    assert entry["latency_ms"] >= 0

    # Log file must contain one JSON line per trace.
    lines = (tmp_path / "telemetry.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["cmd"] == "open chrome"
    assert parsed["status"] == "success"


def test_end_trace_records_failure(tmp_path):
    telemetry = Telemetry()
    telemetry.log_path = str(tmp_path / "telemetry.log")

    trace = telemetry.start_trace("delete file")
    entry = telemetry.end_trace(trace, status="failed", error="Permission denied")

    assert entry["status"] == "failed"
    assert entry["error"] == "Permission denied"

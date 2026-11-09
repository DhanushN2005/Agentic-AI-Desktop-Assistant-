from core.telemetry import TelemetryRecord, TelemetryStore


def test_record_and_summary(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    try:
        store.record(
            TelemetryRecord(
                model_id="test-model",
                engine="ollama",
                agent="simple",
                prompt_tokens=2,
                completion_tokens=3,
                latency_seconds=0.25,
                cost_usd=0.001,
            )
        )
        summary = store.summary()
        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 5
        assert summary["per_engine"]["ollama"]["calls"] == 1
    finally:
        store.close()


def test_export_and_clear(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    try:
        store.record(TelemetryRecord(model_id="m"))
        records = store.export_records()
        assert records[0]["model_id"] == "m"
        assert store.clear() == 1
        assert store.count() == 0
    finally:
        store.close()

"""Token / cost / latency telemetry."""
import json
from types import SimpleNamespace

import pytest

from core.telemetry import pricing
from core.telemetry.report import build_report, render
from core.telemetry.store import TelemetryStore
from core.telemetry.usage import (
    UsageTracker,
    begin_command,
    end_command,
    estimate_tokens,
    extract_usage,
    set_tracker,
    track_llm,
)


@pytest.fixture
def tracker(tmp_path):
    t = UsageTracker(persist=True, db_path=str(tmp_path / "tel.db"))
    previous = set_tracker(t)
    yield t
    set_tracker(previous)


# ----------------------------------------------------------------- usage extraction
def test_extract_usage_handles_every_provider_shape():
    assert extract_usage(SimpleNamespace(prompt_tokens=10, completion_tokens=5)) == (10, 5)        # openai/groq
    assert extract_usage(SimpleNamespace(input_tokens=7, output_tokens=3)) == (7, 3)               # anthropic
    assert extract_usage(SimpleNamespace(prompt_token_count=4, candidates_token_count=2)) == (4, 2)  # gemini
    assert extract_usage({"prompt_eval_count": 21, "eval_count": 9, "done": True}) == (21, 9)      # ollama
    assert extract_usage(None) is None
    assert extract_usage(SimpleNamespace()) is None
    assert extract_usage({"prompt_tokens": "x"}) is None


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd" * 10) == 10


# ----------------------------------------------------------------------------- pricing
def test_local_models_are_free_and_cloud_uses_blended_rate(monkeypatch):
    monkeypatch.delenv("FLEXIE_PRICING_FILE", raising=False)
    assert pricing.cost_usd("ollama", "llama3", 1000, 1000) == (0.0, "local")
    cost, source = pricing.cost_usd("anthropic", "claude", 1000, 1000)
    assert source == "blended" and cost == pytest.approx(2 * pricing.BLENDED_PER_1K["anthropic"])
    assert pricing.cost_usd("unknown-provider", "m", 1000, 1000) == (0.0, "blended")


def test_pricing_file_overrides_with_prefix_matching(tmp_path, monkeypatch):
    f = tmp_path / "prices.json"
    f.write_text(json.dumps({"gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60}}))
    monkeypatch.setenv("FLEXIE_PRICING_FILE", str(f))
    cost, source = pricing.cost_usd("openai", "gpt-4o-mini-2024-07-18", 1_000_000, 1_000_000)
    assert source == "override" and cost == pytest.approx(0.75)
    f.write_text("{not json")
    pricing._cache.clear()
    assert pricing.cost_usd("openai", "gpt-4o-mini", 1000, 0)[1] == "blended"  # bad file never breaks cost


# ------------------------------------------------------------------------- the hook
def test_exact_usage_beats_estimate(tracker):
    with track_llm("groq", "m", prompt_text="x" * 400) as call:
        call.done("y" * 40, SimpleNamespace(prompt_tokens=123, completion_tokens=45))
    entry = list(tracker._calls)[-1]
    assert (entry["prompt_tokens"], entry["completion_tokens"], entry["estimated"]) == (123, 45, False)


def test_missing_usage_falls_back_to_flagged_estimate(tracker):
    with track_llm("groq", "m", prompt_text="x" * 400) as call:
        call.done("y" * 40)
    entry = list(tracker._calls)[-1]
    assert (entry["prompt_tokens"], entry["completion_tokens"], entry["estimated"]) == (100, 10, True)


def test_failed_calls_are_not_recorded_and_exceptions_propagate(tracker):
    with pytest.raises(RuntimeError):
        with track_llm("groq", "m", prompt_text="hi"):
            raise RuntimeError("provider down")
    with track_llm("groq", "m", prompt_text="hi"):
        pass  # never called done(): nothing to record
    assert tracker.summary()["calls"] == 0


def test_telemetry_failure_never_breaks_the_model_call(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    with track_llm("groq", "m", prompt_text="hi") as call:  # must not raise
        call.done("ok")


# ------------------------------------------------------------------ per-command totals
def test_calls_are_attributed_to_the_command_in_flight(tracker):
    t1 = begin_command("cmd-1")
    for _ in range(2):
        with track_llm("openai", "gpt", prompt_text="a" * 400) as c:
            c.done("b" * 80, SimpleNamespace(prompt_tokens=100, completion_tokens=20))
    end_command(t1)
    t2 = begin_command("cmd-2")
    with track_llm("ollama", "llama", prompt_text="a" * 40) as c:
        c.done("b", {"prompt_eval_count": 10, "eval_count": 1})
    end_command(t2)

    one, two = tracker.command("cmd-1"), tracker.command("cmd-2")
    assert (one.calls, one.total_tokens) == (2, 240) and one.cost_usd > 0
    assert (two.calls, two.total_tokens, two.cost_usd) == (1, 11, 0.0)
    with track_llm("groq", "m", prompt_text="x") as c:
        c.done("y")
    assert tracker.command("_unattributed").calls == 1  # outside any command


def test_summary_and_recent_commands(tracker):
    tok = begin_command("c")
    with track_llm("anthropic", "claude", prompt_text="a" * 400) as c:
        c.done("b" * 40, SimpleNamespace(input_tokens=100, output_tokens=10))
    end_command(tok)
    s = tracker.summary()
    assert s["calls"] == 1 and s["total_tokens"] == 110 and s["per_provider"]["anthropic"]["calls"] == 1
    assert tracker.recent_commands(5)[0]["command_id"] == "c"


# -------------------------------------------------------------- persistence + report
def test_calls_persist_with_command_id_and_report_renders(tracker, tmp_path):
    tok = begin_command("persisted-cmd")
    with track_llm("openai", "gpt-4o-mini", prompt_text="a" * 400) as c:
        c.done("b" * 40, SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
    end_command(tok)
    store = TelemetryStore(str(tmp_path / "tel.db"))
    assert store.command_summary("persisted-cmd")["tokens"] == 1100
    report = build_report(store)
    assert report["calls"] == 1 and report["tokens"] == 1100
    assert report["top_commands_by_cost"][0]["command_id"] == "persisted-cmd"
    text = render(report)
    assert "Estimated cost" in text and "gpt-4o-mini" in text


def test_old_databases_are_migrated(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:  # schema from before command_id existed
        conn.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, "
                     "model_id TEXT, engine TEXT, agent TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, "
                     "total_tokens INTEGER, latency_seconds REAL, ttft REAL, cost_usd REAL, energy_joules REAL, "
                     "power_watts REAL, metadata TEXT)")
    store = TelemetryStore(path)
    from core.telemetry.record import TelemetryRecord
    store.record(TelemetryRecord(model_id="m", engine="e", command_id="x", prompt_tokens=1))
    assert store.command_summary("x")["calls"] == 1


# --------------------------------------------------------------- brain integration
def test_brain_openai_compatible_path_records_exact_usage(tracker):
    from core.brain import Brain

    brain = Brain.__new__(Brain)
    brain.deepseek_client = object()
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: resp)))
    tok = begin_command("brain-cmd")
    assert brain._ask_openai_compatible(client, "gpt-4o-mini", "hi", "sys") == "hello"
    end_command(tok)
    cu = tracker.command("brain-cmd")
    assert cu.total_tokens == 55 and cu.estimated_calls == 0 and "openai" in cu.providers


def test_ollama_engine_reports_exact_counts(tracker, monkeypatch):
    import io

    from core.inference.ollama import OllamaEngine

    body = json.dumps({"message": {"content": "hi there"}, "prompt_eval_count": 33, "eval_count": 4}).encode()

    class _Resp(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    engine = OllamaEngine(base_url="http://x")
    monkeypatch.setattr(engine, "available", lambda: True)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp(body))
    out = engine.generate([{"role": "user", "content": "hello"}], model="llama3")
    assert (out.prompt_tokens, out.completion_tokens) == (33, 4)
    entry = list(tracker._calls)[-1]
    assert entry["provider"] == "ollama" and entry["estimated"] is False and entry["cost_usd"] == 0.0


def test_api_usage_endpoint_requires_auth_and_returns_totals(tracker, monkeypatch):
    from fastapi.testclient import TestClient

    from interface.api_server import create_app

    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "t0k")
    tok = begin_command("api-cmd")
    with track_llm("groq", "m", prompt_text="a" * 40) as c:
        c.done("b", SimpleNamespace(prompt_tokens=8, completion_tokens=2))
    end_command(tok)
    client = TestClient(create_app(None))
    assert client.get("/api/flexie/usage").status_code == 401
    data = client.get("/api/flexie/usage", headers={"Authorization": "Bearer t0k"}).json()
    assert data["summary"]["total_tokens"] == 10 and data["recent_commands"][0]["command_id"] == "api-cmd"


# ------------------------------------------------------- orchestrator attribution
def _bare_orchestrator(impl):
    from core.orchestrator import FlexieOrchestrator

    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.logger = __import__("logging").getLogger("t")
    traces = []

    class _TC:
        def start(self, query, **k):
            tr = SimpleNamespace(trace_id=f"trace-{len(traces) + 1}", metadata={}, total_tokens=0)
            traces.append(tr)
            return tr

        def step(self, *a, **k): ...
        def finish(self, *a, **k): ...

    o.trace_collector = _TC()
    o._handle_command_impl = impl
    return o, traces


def test_handle_command_attributes_calls_and_subcommands_share_the_outer_id(tracker):
    def _llm(n):
        with track_llm("openai", "gpt", prompt_text="a" * 40) as c:
            c.done("b", SimpleNamespace(prompt_tokens=n, completion_tokens=1))

    holder = {}

    def impl(cmd, is_subcommand, silent, source, depth):
        _llm(10)
        if cmd == "outer":
            holder["o"].handle_command("inner step", is_subcommand=True)  # planned sub-step
        return "ok"

    o, traces = _bare_orchestrator(impl)
    holder["o"] = o
    o.handle_command("outer")
    cu = tracker.command(traces[0].trace_id)           # the user command: its own + the sub-step's call
    assert cu.calls == 2 and cu.total_tokens == 22
    assert traces[0].total_tokens == 22 and traces[0].metadata["usage"]["calls"] == 2
    o.handle_command("second command")                 # next user command starts a fresh bucket
    assert tracker.command(traces[2].trace_id).calls == 1


def test_command_id_is_cleared_after_the_command_even_on_error(tracker):
    from core.telemetry.usage import current_command

    def impl(*a, **k):
        raise RuntimeError("boom")

    o, _ = _bare_orchestrator(impl)
    with pytest.raises(RuntimeError):
        o.handle_command("x")
    assert current_command() is None

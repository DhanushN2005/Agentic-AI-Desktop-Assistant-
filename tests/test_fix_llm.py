"""Regression tests for the LLM-layer / telemetry / traces fixes (X-3, LM-1 .. LM-17).

Every network client is a fake: no real LLM, no Ollama, no sockets except a loopback bridge test.
"""
from __future__ import annotations

import http.client
import json
import sqlite3
import subprocess
import sys
import threading
import time
import types
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.brain as brain_mod
import core.inference.ollama as _oll
from core.brain import Brain, _Uncacheable
from core.llm_providers import LLMProvider, LLMProviderManager, ProviderStatus
from core.telemetry.usage import UsageTracker, begin_job, end_job, set_tracker, track_llm
from utils.config import Config

_REAL_OLLAMA_AVAILABLE = _oll.ollama_available
ROOT = Path(__file__).resolve().parents[1]
_REAL_SLEEP = time.sleep  # captured at import, before the autouse fixture patches time.sleep


# ----------------------------------------------------------------------------- helpers
def _patch_sleep(monkeypatch, module, fn):
    """Replace ``module.time`` by a proxy so only that module's sleep is faked (threads elsewhere keep sleeping)."""
    proxy = SimpleNamespace(sleep=fn, monotonic=time.monotonic, time=time.time, perf_counter=time.perf_counter)
    monkeypatch.setattr(module, "time", proxy)


def make_brain() -> Brain:
    b = Brain.__new__(Brain)
    for name in ("groq_client", "openai_client", "deepseek_client", "mistral_client", "anthropic_client",
                 "gemini_new_client", "gemini_model", "gemini_chat", "provider_manager",
                 "context_compiler", "vector_store", "memory_manager"):
        setattr(b, name, None)
    b.system_prompt = "sys"
    b._cache = OrderedDict()
    b._cache_max = 64
    b._cache_ttl = 45.0
    return b


@pytest.fixture(autouse=True)
def offline_world(monkeypatch):
    """Online, no local Ollama, auto provider, no search: tests opt in to what they need."""
    import core.inference.ollama as oll

    oll.reset_health_cache()
    monkeypatch.setattr(brain_mod, "is_online", lambda: True)
    monkeypatch.setattr(oll, "ollama_available", lambda *a, **k: False)
    monkeypatch.setattr(Config, "ACTIVE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(Config, "LOCAL_FIRST", False, raising=False)
    monkeypatch.setattr(Config, "ENGINE", "auto", raising=False)
    for key in ("GROQ_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MISTRAL_API_KEY",
                "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):  # never touch the developer's real keys / network
        monkeypatch.setattr(Config, key, "", raising=False)
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Brain, "_ddg_search", lambda self, p: "ddg-fallback")
    _patch_sleep(monkeypatch, brain_mod, lambda s: pytest.fail(f"unexpected sleep({s})"))
    yield
    oll.reset_health_cache()


@pytest.fixture(autouse=True)
def tracker():
    t = UsageTracker(persist=False)
    prev = set_tracker(t)
    yield t
    set_tracker(prev)


def completion(text, usage=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage)


def fake_client(*responses, stream_chunks=None):
    """OpenAI-style client. Items are str (reply) or Exception (raised)."""
    queue = list(responses)
    calls: list[dict] = []

    def create(**kw):
        calls.append(kw)
        if kw.get("stream"):
            return stream_chunks(kw) if callable(stream_chunks) else iter(stream_chunks)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return completion(item)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), calls=calls)


def chunk(text=None, usage=None, choices=True):
    if not choices:
        return SimpleNamespace(choices=[], usage=usage)
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=usage)


# =============================================================== X-3 / LM-2 failures never cached
def test_failure_text_is_never_cached():
    b = make_brain()
    n = {"c": 0}

    def impl(*a, **k):
        n["c"] += 1
        return _Uncacheable("All AI providers are unavailable right now")

    b._ask_impl = impl
    b.ask("explain recursion")
    b.ask("explain recursion")
    assert n["c"] == 2 and len(b._cache) == 0


def test_known_failure_markers_not_cached_even_without_flag():
    b = make_brain()
    replies = ["I've searched for you, Dhanush, but nothing", "real answer", "unused"]
    b._ask_impl = lambda *a, **k: replies.pop(0)
    assert b.ask("q one").startswith("I've searched")
    assert b.ask("q one") == "real answer"
    assert b.ask("q one") == "real answer" and replies == ["unused"]  # real answers ARE cached


def test_real_chain_failure_result_is_not_cached():
    b = make_brain()  # no providers at all: ddg fallback
    assert b.ask("tell me a story") == "ddg-fallback"
    assert len(b._cache) == 0


def test_offline_failure_message_not_cached(monkeypatch):
    monkeypatch.setattr(brain_mod, "is_online", lambda: False)
    b = make_brain()
    out = b.ask("tell me a story")
    assert out.startswith("All AI providers are unavailable") and len(b._cache) == 0


def test_cache_ttl_expires():
    b = make_brain()
    b._cache_ttl = 0.05
    n = {"c": 0}

    def impl(*a, **k):
        n["c"] += 1
        return f"answer {n['c']}"

    b._ask_impl = impl
    assert b.ask("what is rust") == "answer 1"
    assert b.ask("what is rust") == "answer 1"
    b._cache_ttl = -1.0                  # any stored entry is now older than the TTL
    assert b.ask("what is rust") == "answer 2"


@pytest.mark.parametrize("prompt", [
    "what is the time", "what's the date", "weather in Pune", "any news", "what is happening today",
    "do it now", "latest iphone", "WEATHER please",
])
def test_time_sensitive_prompts_bypass_cache(prompt):
    b = make_brain()
    n = {"c": 0}
    b._ask_impl = lambda *a, **k: (n.__setitem__("c", n["c"] + 1), f"r{n['c']}")[1]
    b.ask(prompt)
    b.ask(prompt)
    assert n["c"] == 2 and len(b._cache) == 0


def test_cache_is_thread_safe_under_eviction():
    b = make_brain()
    b._cache_max = 3
    b._ask_impl = lambda prompt, *a, **k: f"ans-{prompt}"
    errors = []

    def worker(i):
        try:
            for j in range(150):
                b.ask(f"prompt {(i * 7 + j) % 40}")
        except Exception as e:  # pragma: no cover - the bug would land here
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(b._cache) <= 3


# =============================================================== LM-1 cache key
def test_cache_key_includes_image_path_mtime_use_chat_and_provider(tmp_path, monkeypatch):
    b = make_brain()
    img = tmp_path / "shot.png"
    img.write_bytes(b"one")
    seen = []
    b._ask_impl = lambda prompt, img_path, *a, **k: (seen.append(img_path), f"a{len(seen)}")[1]
    assert b.ask("what is on my screen", img_path=str(img)) == "a1"
    assert b.ask("what is on my screen", img_path=str(img)) == "a1"          # same file -> cached
    other = tmp_path / "other.png"
    other.write_bytes(b"two")
    assert b.ask("what is on my screen", img_path=str(other)) == "a2"        # different image
    img.write_bytes(b"three-longer")                                         # same path, new content
    assert b.ask("what is on my screen", img_path=str(img)) == "a3"
    n = len(seen)
    b.ask("hello there", use_chat=True)
    b.ask("hello there", use_chat=False)
    assert len(seen) == n + 2                                                # use_chat is part of the key
    monkeypatch.setattr(Config, "ACTIVE_PROVIDER", "groq", raising=False)
    n = len(seen)
    b.ask("what is on my screen", img_path=str(other))
    assert len(seen) == n + 1                                                # provider changed -> miss


def test_missing_image_is_not_cached():
    b = make_brain()
    n = {"c": 0}
    b._ask_impl = lambda *a, **k: (n.__setitem__("c", n["c"] + 1), "x")[1]
    b.ask("describe", img_path="Z:/does/not/exist.png")
    b.ask("describe", img_path="Z:/does/not/exist.png")
    assert n["c"] == 2


# =============================================================== LM-3 clients: no SDK retries, explicit timeouts
def test_sdk_clients_built_with_zero_retries_and_timeout(monkeypatch):
    built = {}

    def factory(label):
        def ctor(**kw):
            built.setdefault(label, []).append(kw)
            return SimpleNamespace()
        return ctor

    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=factory("groq")))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=factory("openai")))
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=factory("anthropic")))
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setattr(Config, k, "k-" + k, raising=False)
    monkeypatch.setattr(Config, "LLM_REQUEST_TIMEOUT", 5.0, raising=False)
    b = make_brain()
    b._init_all_providers()
    all_kwargs = [kw for lst in built.values() for kw in lst]
    assert len(all_kwargs) == 5                       # groq + openai + deepseek + mistral + anthropic
    assert all(kw["max_retries"] == 0 and kw["timeout"] == 5.0 for kw in all_kwargs)


def test_manager_clients_built_with_zero_retries_and_cached(monkeypatch):
    built = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kw: built.append(kw) or SimpleNamespace()))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-123456")
    m = LLMProviderManager()
    p = next(x for x in m.providers if x.name == "openai")
    c1 = m._client("openai", p)
    c2 = m._client("openai", p)
    assert c1 is c2 and len(built) == 1
    assert built[0]["max_retries"] == 0 and built[0]["timeout"] == p.timeout


def test_anthropic_and_gemini_calls_carry_a_timeout_and_callers_max_tokens(monkeypatch):
    b = make_brain()
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(text="hi")], usage=None)

    b.anthropic_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert b._ask_anthropic("hello", "sys", None, max_tokens=77) == "hi"
    assert seen["max_tokens"] == 77 and seen["timeout"] == Brain._request_timeout()
    b._ask_anthropic("hello", "sys", None)
    assert seen["max_tokens"] == 2048


# =============================================================== LM-4 no sleeps, fail fast
def test_rate_limited_provider_falls_through_without_sleeping():
    b = make_brain()
    b.groq_client = fake_client(RuntimeError("Error 429 rate limit"))
    b.openai_client = fake_client("from openai")
    assert b.ask("write a haiku") == "from openai"          # time.sleep is patched to fail the test


def test_fixed_provider_rate_limit_does_not_sleep_or_raise(monkeypatch):
    monkeypatch.setattr(Config, "ACTIVE_PROVIDER", "groq", raising=False)
    b = make_brain()
    b.groq_client = fake_client(RuntimeError("429 too many requests"))
    assert b.ask("write a haiku") == "ddg-fallback"
    assert len(b.groq_client.calls) == 1                    # one attempt, not 4


def test_ask_retries_a_network_blip_at_most_once(monkeypatch):
    sleeps = []
    _patch_sleep(monkeypatch, brain_mod, lambda s: sleeps.append(s))
    b = make_brain()
    n = {"c": 0}

    def impl(*a, **k):
        n["c"] += 1
        raise ConnectionError("connection reset")

    b._ask_impl = impl
    with pytest.raises(ConnectionError):
        b.ask("hello there")
    assert n["c"] == 2 and sleeps == [0.25]
    n["c"] = 0

    def impl429(*a, **k):
        n["c"] += 1
        raise RuntimeError("429 rate limit")

    b._ask_impl = impl429
    with pytest.raises(RuntimeError):
        b.ask("hello again")
    assert n["c"] == 1                                       # rate limits are never retried


def test_model_hub_retry_is_not_multiplied(monkeypatch):
    from unittest.mock import MagicMock

    import core.model_hub as hub_mod
    from core.model_hub import ModelHub, TaskType

    sleeps = []
    _patch_sleep(monkeypatch, hub_mod, lambda s: sleeps.append(s))
    hub = ModelHub()
    hub.check_ollama_health = lambda: (False, [])
    brain = MagicMock()
    brain.ask.side_effect = Exception("429 Too Many Requests")
    assert hub.route_and_ask("x", task=TaskType.CODE, brain=brain) == ""
    assert brain.ask.call_count == 2 and len(sleeps) == 1 and sleeps[0] < 0.5


# =============================================================== LM-5 validation of local / JSON answers
def test_json_caller_rejects_invalid_local_and_uses_next_provider(monkeypatch):
    monkeypatch.setattr(Config, "LOCAL_FIRST", True, raising=False)
    b = make_brain()
    seen = {}

    def local(prompt, sys_p, max_tokens, history=None, timeout=None):
        seen["timeout"] = timeout
        return "sure! the intent is app_op"                  # not JSON

    b._ask_local_engine = local
    b.groq_client = fake_client('{"intent": "app_op", "confidence": 0.9}')
    out = b.ask("route this", system_override="You are a tool router. Return ONLY valid JSON.")
    assert json.loads(out)["intent"] == "app_op"
    assert seen["timeout"] == 6.0                            # short local timeout for routing calls


def test_plain_caller_keeps_long_local_timeout_and_accepts_prose(monkeypatch):
    monkeypatch.setattr(Config, "LOCAL_FIRST", True, raising=False)
    b = make_brain()
    seen = {}
    b._ask_local_engine = lambda p, s, m, h=None, timeout=None: (seen.update(t=timeout), "plain local answer")[1]
    assert b.ask("chat with me") == "plain local answer" and seen["t"] == 30.0


@pytest.mark.parametrize("bad", ["", "   \n", None])
def test_empty_local_answer_is_never_accepted(monkeypatch, bad):
    monkeypatch.setattr(Config, "LOCAL_FIRST", True, raising=False)
    b = make_brain()
    b._ask_local_engine = lambda *a, **k: bad
    b.openai_client = fake_client("cloud answer")
    assert b.ask("hello") == "cloud answer"


def test_expect_json_when_nothing_valid_returns_best_effort_uncached():
    b = make_brain()
    b.groq_client = fake_client("not json at all")
    out = b.ask("route", expect_json=True)
    assert out == "not json at all" and len(b._cache) == 0   # caller (router) falls back on its own
    b2 = make_brain()
    assert b2.ask("route", expect_json=True) == ""           # nothing at all -> empty, no ddg prose


def test_custom_validate_hook():
    b = make_brain()
    b.groq_client = fake_client("42x")
    b.openai_client = fake_client("42")
    assert b.ask("number?", validate=str.isdigit) == "42"


# =============================================================== LM-6 streaming
def _stream_brain(**clients):
    b = make_brain()
    for k, v in clients.items():
        setattr(b, k, v)
    return b


def test_stream_failure_after_first_chunk_does_not_fall_back():
    def broken(kw):
        yield chunk("Hello ")
        yield chunk("wor")
        raise RuntimeError("connection dropped")

    b = _stream_brain(groq_client=fake_client(stream_chunks=broken), openai_client=fake_client("FULL ANSWER"))
    b.ask = lambda *a, **k: pytest.fail("must not call the non-stream fallback after chunks were yielded")
    assert "".join(b.ask_stream("hi there")) == "Hello wor"
    assert b.openai_client.calls == []                       # never asked a second provider


def test_stream_failure_before_first_chunk_falls_to_next_provider():
    def broken(kw):
        raise RuntimeError("503 service unavailable")
        yield  # pragma: no cover

    b = _stream_brain(groq_client=fake_client(stream_chunks=broken),
                      openai_client=fake_client(stream_chunks=[chunk("from "), chunk("openai")]))
    assert "".join(b.ask_stream("hi there")) == "from openai"


def test_empty_stream_falls_back_to_non_stream_ask():
    b = _stream_brain(groq_client=fake_client(stream_chunks=[chunk(None)]))
    b.ask = lambda *a, **k: "non-stream answer"
    assert "".join(b.ask_stream("hi")) == "non-stream answer"


def test_local_first_stream_and_consistent_skip_local(monkeypatch):
    import core.inference.ollama as oll

    monkeypatch.setattr(Config, "LOCAL_FIRST", True, raising=False)
    monkeypatch.setattr(oll, "ollama_available", lambda *a, **k: True)
    b = make_brain()
    models = []
    b._ollama_chat_stream = lambda model, messages, temperature=0.7: (models.append(model), iter(["loc", "al"]))[1]
    assert "".join(b.ask_stream("hello")) == "local"
    assert models == [Config.OLLAMA_MODEL] and models[0] != "deepseek-r1"   # no hard-coded model

    # local produced nothing -> non-stream ask() runs WITHOUT trying local a second time
    b2 = make_brain()
    b2._ollama_chat_stream = lambda model, messages, temperature=0.7: iter(())
    got = {}
    b2.ask = lambda *a, **k: (got.update(k), "cloud-ish")[1]
    assert "".join(b2.ask_stream("hello")) == "cloud-ish" and got["skip_local"] is True


def test_ollama_chat_stream_propagates_errors_and_records_failure(tracker, monkeypatch):
    b = make_brain()

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(brain_mod, "urlopen", boom)
    with pytest.raises(OSError):
        list(b._ollama_chat_stream("m", [{"role": "user", "content": "x"}]))
    assert tracker.summary()["failed_calls"] == 1


# =============================================================== LM-7 stream telemetry
def test_stream_latency_measured_from_request_start_and_exact_usage(tracker):
    waits = {}

    def slow(kw):
        waits["kw"] = kw
        real_sleep(0.06)           # time before the first byte counts
        yield chunk("a")
        yield chunk("b")
        yield chunk(choices=False, usage=SimpleNamespace(prompt_tokens=11, completion_tokens=2))

    real_sleep = _REAL_SLEEP
    b = _stream_brain(groq_client=fake_client(stream_chunks=slow))
    assert "".join(b.ask_stream("hi")) == "ab"
    entry = list(tracker._calls)[-1]
    assert entry["latency_seconds"] >= 0.05                  # was ~0 before the fix
    assert (entry["prompt_tokens"], entry["completion_tokens"], entry["estimated"]) == (11, 2, False)
    assert waits["kw"]["stream_options"] == {"include_usage": True}


def test_stream_without_usage_support_retries_without_stream_options(tracker):
    calls = []

    def create(**kw):
        calls.append(kw)
        if "stream_options" in kw:
            raise TypeError("unexpected keyword argument 'stream_options'")
        return iter([chunk("ok")])

    b = _stream_brain(groq_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    assert "".join(b.ask_stream("hi")) == "ok" and len(calls) == 2



# =============================================================== LM-8 / LM-9 Groq empty, Gemini system prompt
@pytest.mark.parametrize("empty", [None, "", "  "])
def test_groq_empty_reply_falls_through_and_never_returns_none(empty, tracker):
    b = make_brain()
    b.groq_client = fake_client(empty)
    b.openai_client = fake_client("openai answer")
    out = b.ask("explain monads")
    assert out == "openai answer" and out is not None
    s = tracker.summary()
    assert s["failed_calls"] == 1 and s["per_provider"]["groq"]["failed_calls"] == 1


def test_all_empty_returns_a_string_not_none():
    b = make_brain()
    b.groq_client = fake_client(None)
    out = b.ask("explain monads")
    assert isinstance(out, str) and out == "ddg-fallback"


def _fake_genai(captured):
    mod = types.ModuleType("google.genai")

    class _Models:
        def generate_content(self, model, contents, config=None):
            captured.update(model=model, contents=contents, config=config)
            return SimpleNamespace(text="gemini says hi", usage_metadata=None)

    class Client:
        def __init__(self, api_key=None, http_options=None):
            captured["api_key"], captured["http_options"] = api_key, http_options
            self.models = _Models()

    mod.Client = Client
    mod.types = SimpleNamespace(HttpOptions=lambda timeout: ("http", timeout))
    return mod


def test_gemini_lazy_and_always_sends_system_instruction(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "google.genai", _fake_genai(captured))
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "g-key", raising=False)
    monkeypatch.setattr(Config, "LLM_REQUEST_TIMEOUT", 4.0, raising=False)
    b = make_brain()
    b._gemini_enabled = True
    assert b.gemini_new_client is None                       # nothing built until first use
    assert b.ask("hello gemini", system_override=None) == "gemini says hi"
    assert captured["config"]["system_instruction"] == "sys"  # the DEFAULT prompt is sent too (LM-9)
    assert captured["http_options"] == ("http", 15000)        # explicit timeout (ms); Gemini needs >= 10 s, clamped up to 15 s
    b._cache.clear()
    b.ask("another one", system_override="custom persona", max_tokens=33)
    assert captured["config"] == {"system_instruction": "custom persona", "max_output_tokens": 33}


def test_gemini_history_and_image_handle_closed(monkeypatch, tmp_path):
    from PIL import Image

    captured = {}
    monkeypatch.setitem(sys.modules, "google.genai", _fake_genai(captured))
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "g-key", raising=False)
    path = tmp_path / "s.png"
    Image.new("RGB", (4, 4)).save(path)
    b = make_brain()
    b._gemini_enabled = True
    out = b.ask("what is this", img_path=str(path), history=[{"role": "user", "content": "earlier"}])
    assert out == "gemini says hi"
    text, img = captured["contents"]
    assert text.startswith("Recent conversation:") and "earlier" in text
    assert img.fp is None                                    # Image.open handle closed (LM-17)


def test_missing_gemini_sdk_is_not_retried_every_call(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.genai", None)   # import raises ImportError
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "g-key", raising=False)
    b = make_brain()
    b._gemini_enabled = True
    assert b.ask("hello") == "ddg-fallback"
    assert b._gemini_failed_key == "g-key" and b._get_gemini_client() is None


# =============================================================== LM-10 no second provider pass; LM-11 breaker
def test_brain_excludes_already_tried_providers_from_manager_pass():
    b = make_brain()
    b.groq_client = fake_client(RuntimeError("boom"))
    got = {}
    reports = []

    def query(prompt, **kw):
        got.update(kw)
        return "", "none"

    b.provider_manager = SimpleNamespace(query=query, allow=lambda n: True,
                                         report=lambda n, ok, err="": reports.append((n, ok)))
    b.ask("hello")
    assert "groq" in got["exclude"]
    assert ("groq", False) in reports                        # shared circuit breaker fed


def test_open_circuit_provider_is_skipped():
    b = make_brain()
    b.groq_client = fake_client("should not be called")
    b.openai_client = fake_client("openai")
    b.provider_manager = SimpleNamespace(query=lambda *a, **k: ("", "none"),
                                         allow=lambda n: n != "groq", report=lambda *a, **k: None)
    assert b.ask("hello") == "openai" and b.groq_client.calls == []


def test_manager_query_is_a_single_pass_and_honours_exclude(monkeypatch):
    monkeypatch.setenv("ACTIVE_PROVIDER", "auto")
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.setenv(k, "k-123456789")
    for k in ("DEEPSEEK_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    m = LLMProviderManager()
    called = []

    def fail(provider, *a, **k):
        called.append(provider.name)
        raise RuntimeError("down")

    m._call_provider = fail
    assert m.query("x") == ("", "none")
    assert sorted(called) == ["groq", "mistral", "openai"]   # each exactly once
    called.clear()
    m.query("x", exclude={"groq", "openai"})
    assert called == ["mistral"]


def test_circuit_breaker_recovers_after_cooldown(monkeypatch):
    monkeypatch.setenv("FIX_LLM_KEY", "k")
    p = LLMProvider(name="t", api_key_env="FIX_LLM_KEY", model="m", priority=1, cooldown_seconds=100.0)
    assert p.is_available
    for _ in range(3):
        p.record_failure("e")
    assert p.status == ProviderStatus.UNAVAILABLE and not p.is_available
    t0 = p.unavailable_since
    import core.llm_providers as lp

    def at(t):
        monkeypatch.setattr(lp, "time", SimpleNamespace(time=lambda: t))

    at(t0 + 99.0)
    assert not p.is_available                                # still cooling down
    at(t0 + 101.0)
    assert p.is_available                                    # half-open trial allowed
    p.record_failure("still down")                           # trial failed -> re-open at once
    assert not p.is_available
    at(p.unavailable_since + 101.0)
    assert p.is_available
    p.record_success()                                       # trial worked -> closed again
    assert p.status == ProviderStatus.HEALTHY and p.consecutive_failures == 0 and p.is_available


def test_cooldown_constant_is_used_and_providers_are_not_shared():
    m1, m2 = LLMProviderManager(), LLMProviderManager()
    assert all(p.cooldown_seconds == LLMProviderManager.COOLDOWN_SECONDS for p in m1.providers)
    m1.providers[0].record_failure("x")
    assert m2.providers[0].consecutive_failures == 0
    assert LLMProviderManager.DEFAULT_PROVIDERS[0].consecutive_failures == 0
    assert m1.providers[0] is not LLMProviderManager.DEFAULT_PROVIDERS[0]


def test_default_models_align_with_config(monkeypatch):
    for k in ("GEMINI_MODEL", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(k, raising=False)
    m = LLMProviderManager()
    models = {p.name: p.model for p in m.providers}
    assert models["gemini"] == Config.GEMINI_MODEL and models["anthropic"] == Config.ANTHROPIC_MODEL
    assert "1.5" not in models["gemini"] and "20241022" not in models["anthropic"]


# =============================================================== LM-12 local message assembly
def test_local_engine_uses_cloud_message_assembly(monkeypatch):
    got = {}

    class FakeEngine:
        def __init__(self, timeout=None):
            got["timeout"] = timeout

        def available(self):
            return True

        def generate(self, messages, model=None, max_tokens=0, temperature=0.3):
            got["messages"] = messages
            return SimpleNamespace(text="  local ok ", model="tiny")

    monkeypatch.setattr("core.inference.OllamaEngine", FakeEngine)
    monkeypatch.setattr(Config, "CONVERSATION_HISTORY_TURNS", 3, raising=False)
    history = [
        {"role": "user", "content": "old"},                  # beyond the limit
        {"role": "assistant", "content": "reply"},
        {"role": "tool", "content": "noise"},                # filtered role
        {"role": "user", "content": "the question"},         # duplicate of the current prompt
    ]
    b = make_brain()
    assert b._ask_local_engine("the question", "sys", None, history, timeout=9.0) == "  local ok "
    assert got["messages"] == Brain._build_messages("sys", "the question", history)
    assert [m["content"] for m in got["messages"]] == ["sys", "reply", "the question"]
    assert got["timeout"] == 9.0


def test_local_engine_blank_text_is_none(monkeypatch):
    class FakeEngine:
        def __init__(self, timeout=None): ...
        def available(self): return True
        def generate(self, *a, **k): return SimpleNamespace(text="   ", model="m")

    monkeypatch.setattr("core.inference.OllamaEngine", FakeEngine)
    assert make_brain()._ask_local_engine("p", "s", None) is None


# =============================================================== LM-13 model hub
class _Resp:
    status = 200

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_hub_health_uses_base_url_and_is_cached_and_shared(monkeypatch):
    from core.model_hub import ModelHub

    urls = []
    body = json.dumps({"models": [{"name": "nomic-embed-text"}, {"name": "llama3.2:3b"}]}).encode()

    def fake_urlopen(req, timeout=None):
        urls.append(req.full_url)
        return _Resp(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(Config, "OLLAMA_URL", "http://localhost:11434/api/generate", raising=False)
    monkeypatch.setattr(_oll, "ollama_available", _REAL_OLLAMA_AVAILABLE)   # undo the autouse stub
    monkeypatch.setattr("core.model_hub.ollama_available", _REAL_OLLAMA_AVAILABLE)
    _oll.reset_health_cache()
    hub = ModelHub()
    healthy, models = hub.check_ollama_health()
    assert healthy and models == ["nomic-embed-text", "llama3.2:3b"]
    assert set(urls) == {"http://localhost:11434/api/tags"}                  # not '/api/generate/api/tags'
    n = len(urls)
    hub.check_ollama_health()
    hub.check_ollama_health()
    assert len(urls) == n                                                    # 30 s TTL: no per-call probe
    assert _REAL_OLLAMA_AVAILABLE("http://localhost:11434") is True and len(urls) == n   # one shared cache
    assert Brain._ollama_base() == "http://localhost:11434"


def test_hub_marks_ollama_down_when_unreachable(monkeypatch):
    from core.model_hub import ModelHub

    def refuse(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr(_oll, "ollama_available", _REAL_OLLAMA_AVAILABLE)
    monkeypatch.setattr("core.model_hub.ollama_available", _REAL_OLLAMA_AVAILABLE)
    _oll.reset_health_cache()
    assert ModelHub().check_ollama_health() == (False, [])


def test_hub_never_picks_embedding_model_and_passes_options():
    from core.model_hub import ModelHub, TaskType

    hub = ModelHub()
    hub.check_ollama_health = lambda: (True, ["nomic-embed-text:latest", "mistral:7b"])
    seen = {}
    hub._execute_ollama = lambda prompt, model, system=None, **kw: (seen.update(model=model, **kw), "local")[1]
    assert hub.route_and_ask("hi", task=TaskType.ROUTE) == "local"
    assert seen["model"] == "mistral:7b" and seen["max_tokens"] == 512 and seen["temperature"] == 0.1
    hub.check_ollama_health = lambda: (True, ["nomic-embed-text:latest"])     # only an embedder: skip local
    assert hub.route_and_ask("hi", task=TaskType.ROUTE) == ""


def test_execute_ollama_uses_generate_endpoint_options_and_ledger(monkeypatch, tracker):
    from core.model_hub import ModelHub

    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["url"], sent["payload"] = req.full_url, json.loads(req.data)
        return _Resp(json.dumps({"response": " hi ", "prompt_eval_count": 7, "eval_count": 3}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    hub = ModelHub()
    tok = begin_job("job-1")
    assert hub._execute_ollama("p", "m", max_tokens=99, temperature=0.2) == "hi"
    end_job(tok)
    assert sent["url"] == "http://localhost:11434/api/generate"
    assert sent["payload"]["options"] == {"num_predict": 99, "temperature": 0.2}
    rep = hub.tracker.get_job_report("job-1")
    assert (rep["prompt_tokens"], rep["completion_tokens"], rep["calls"]) == (7, 3, 1)


def test_token_tracker_does_not_double_count_with_ledger(tracker):
    from core.model_hub import TokenTracker

    tt = TokenTracker()
    tok = begin_job("j")
    with track_llm("groq", "m", prompt_text="a" * 40) as c:
        c.done("b" * 40)
    end_job(tok)
    assert tt.get_job_report("j")["calls"] == 1              # the ledger is the only source
    assert tt.get_summary_report()["total_tokens"] == tracker.summary()["total_tokens"]
    tt.record("x", "code", 10, 5, job_id="j2")               # explicit records still work
    assert tt.get_job_report("j2")["total_tokens"] == 15


def test_bridge_threaded_constant_time_auth_history_and_stream():
    from core.model_hub import ModelHub, OpenAIBridgeServer

    hub = ModelHub()
    started, release = threading.Event(), threading.Event()
    seen = {}

    def slow(prompt, task=None, system_override=None, history=None, **kw):
        seen.update(prompt=prompt, history=history, system=system_override)
        started.set()
        release.wait(2.0)
        return "bridge answer"

    hub.route_and_ask = slow
    srv = OpenAIBridgeServer(hub, port=0, token="s3cret")
    assert srv.start()
    port = srv._server.server_address[1]
    try:
        results = {}

        def post(stream):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            body = json.dumps({"stream": stream, "messages": [
                {"role": "system", "content": "be nice"}, {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"}, {"role": "user", "content": "second"}]})
            c.request("POST", "/v1/chat/completions", body, {"Authorization": "Bearer s3cret"})
            r = c.getresponse()
            results["post"] = (r.status, r.getheader("Content-Type"), r.read().decode())

        t = threading.Thread(target=post, args=(True,))
        t.start()
        assert started.wait(2.0)
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)        # served WHILE the first is blocked
        c.request("GET", "/v1/models", headers={"Authorization": "Bearer s3cret"})
        assert c.getresponse().status == 200
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        c.request("GET", "/v1/models", headers={"Authorization": "Bearer wrong"})
        assert c.getresponse().status == 401
        release.set()
        t.join(3)
    finally:
        srv.stop()
    status, ctype, text = results["post"]
    assert status == 200 and ctype == "text/event-stream" and "bridge answer" in text and "[DONE]" in text
    assert seen["system"] == "be nice" and seen["prompt"] == "second"
    assert seen["history"] == [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ok"}]
    assert "compare_digest" in Path(ROOT / "core" / "model_hub.py").read_text(encoding="utf-8")


# =============================================================== LM-14 event bus + collector
def _fresh_bus():
    from core.event_bus.bus import EventBus

    bus = object.__new__(EventBus)
    bus._init_bus()
    return bus


def test_event_bus_is_fifo_within_equal_priority_and_respects_priority():
    from core.event_bus.bus import Event

    bus = _fresh_bus()
    order = []
    gate, entered = threading.Event(), threading.Event()

    def cb(ev):
        if ev.name == "block":
            entered.set()
            gate.wait(2.0)
        else:
            order.append(ev.payload["i"])

    bus.subscribe("block", cb)
    bus.subscribe("e", cb)
    bus.publish(Event("block", priority=0))
    assert entered.wait(2.0)
    for i in range(40):
        bus.publish(Event("e", {"i": i}, priority=2))
    bus.publish(Event("e", {"i": "urgent"}, priority=0))
    gate.set()
    deadline = time.time() + 2.0
    while len(order) < 41 and time.time() < deadline:
        _REAL_SLEEP(0.01)
    bus.shutdown()
    assert order[0] == "urgent" and order[1:] == list(range(40))


class _FakeBus:
    def __init__(self):
        self.h = {}

    def subscribe(self, name, cb):
        self.h[name] = cb

    def publish(self, name, payload=None, trace_id=None):
        ev = SimpleNamespace(name=name, payload=payload or {}, trace_id=trace_id)
        self.h[name](ev)


def test_collector_attaches_events_by_trace_id(tmp_path):
    from core.traces import TraceCollector, TraceStore

    store = TraceStore(tmp_path / "t.db")
    c = TraceCollector(store)
    bus = _FakeBus()
    c.subscribe(bus)
    t1, t2 = c.start("first"), c.start("second")
    bus.publish("INFERENCE_END", {"trace_id": t1.trace_id, "m": 1})
    bus.publish("TOOL_CALL_END", {"x": 1}, trace_id=t1.trace_id)           # id carried on the event object
    bus.publish("INFERENCE_END", {"m": 2})                                  # ambiguous: dropped, not guessed
    assert len(t1.steps) == 2 and len(t2.steps) == 0
    bus.publish("TRACE_COMPLETE", {"trace_id": t1.trace_id, "result": "r1", "outcome": "success"})
    assert store.get(t1.trace_id).result == "r1" and t2.trace_id in c._active
    bus.publish("INFERENCE_END", {"m": 3})                                  # now exactly one active trace
    assert len(t2.steps) == 1


def test_collector_reaps_traces_that_never_finish(tmp_path):
    from core.traces import TraceCollector, TraceStore

    store = TraceStore(tmp_path / "t.db")
    c = TraceCollector(store, active_ttl=100.0)
    t = c.start("never finishes")
    assert c.reap(now=t.started_at + 50) == 0 and t.trace_id in c._active
    assert c.reap(now=t.started_at + 101) == 1
    assert t.trace_id not in c._active and store.get(t.trace_id).outcome == "abandoned"


def test_event_captures_trace_id_from_context():
    from core.event_bus.bus import Event, current_trace_id

    current_trace_id.set(None)  # an earlier collector.start() in this thread may have set one
    tok = current_trace_id.set("abc")
    try:
        assert Event("x").trace_id == "abc" and Event("x", {"trace_id": "zzz"}).trace_id == "zzz"
    finally:
        current_trace_id.reset(tok)
    assert Event("x").trace_id is None


# =============================================================== LM-15 failures in telemetry
def test_failed_calls_recorded_but_excluded_from_tokens_and_cost(tracker):
    with track_llm("groq", "m", prompt_text="a" * 40) as c:
        c.done("b" * 40)
    with pytest.raises(RuntimeError):
        with track_llm("groq", "m", prompt_text="a" * 40):
            _REAL_SLEEP(0.02)
            raise RuntimeError("boom")
    s = tracker.summary()
    assert s["calls"] == 1 and s["failed_calls"] == 1 and s["failure_rate"] == 0.5
    assert s["total_tokens"] == 20 and s["per_provider"]["groq"]["failed_calls"] == 1
    failed = [e for e in tracker._calls if e["failed"]][0]
    assert failed["error"] == "RuntimeError" and failed["total_tokens"] == 0 and failed["cost_usd"] == 0.0
    assert failed["latency_seconds"] >= 0.015                    # latency of the failure is kept
    assert s["latency_p95_s"] >= 0.015


def test_generator_exit_is_not_a_failure(tracker):
    def gen():
        with track_llm("groq", "m", prompt_text="x"):
            yield 1

    g = gen()
    next(g)
    g.close()
    assert tracker.summary()["failed_calls"] == 0


def test_failures_persisted_and_reported(tmp_path):
    from core.telemetry.report import build_report, render

    t = UsageTracker(persist=True, db_path=str(tmp_path / "t.db"))
    store = t._get_store()
    prev = set_tracker(t)
    try:
        with pytest.raises(ValueError):
            with track_llm("x", "m"):
                raise ValueError("bad")
        with track_llm("x", "m", prompt_text="a" * 40) as c:
            c.done("b" * 40)
    finally:
        set_tracker(prev)
    rep = build_report(store)
    assert rep["failed_calls"] == 1 and rep["calls"] == 1 and rep["failure_rate"] == 0.5
    assert rep["tokens"] == 20
    assert rep["per_engine"]["x"]["failures"] == 1 and "failed: 1" in render(rep)
    assert store.summary()["failed_calls"] == 1


def test_old_telemetry_db_is_migrated_with_failed_column(tmp_path):
    from core.telemetry.record import TelemetryRecord
    from core.telemetry.store import TelemetryStore

    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL, "
                     "model_id TEXT, engine TEXT, agent TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, "
                     "total_tokens INTEGER, latency_seconds REAL, ttft REAL, cost_usd REAL, energy_joules REAL, "
                     "power_watts REAL, metadata TEXT, command_id TEXT)")
        conn.execute("INSERT INTO telemetry (timestamp, model_id, engine, total_tokens) VALUES (?, 'm', 'e', 5)",
                     (time.time(),))
    s = TelemetryStore(path)
    s.record(TelemetryRecord(model_id="m", engine="e", failed=True))
    sm = s.summary()
    assert sm["total_calls"] == 1 and sm["failed_calls"] == 1 and sm["total_tokens"] == 5


# =============================================================== LM-16 lazy Google SDKs
def test_import_core_brain_loads_no_google_sdk():
    code = ("import sys, core.brain; "
            "bad=[m for m in sys.modules if m in ('google.genai','google.generativeai')]; "
            "print('BAD' if bad else 'CLEAN')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert "CLEAN" in out.stdout, out.stdout + out.stderr[-500:]


def test_deprecated_sdk_path_removed():
    src = (ROOT / "core" / "brain.py").read_text(encoding="utf-8")
    assert "import google.generativeai" not in src and "genai_legacy" not in src


# =============================================================== LM-17 low items
def test_secret_redaction_in_errors_and_traces(tmp_path):
    from core.telemetry.redact import redact_secrets
    from core.traces import Trace, TraceStep, TraceStore
    from core.traces.trace import StepType

    msg = "401 for key sk-abcdefghijklmnop1234 and AIzaSyA1234567890abcdefghijklm; Bearer abcdefghijklmnopqrstuv"
    red = redact_secrets(msg)
    assert "abcdefghijklmnop1234" not in red and "AIzaSy" not in red and "abcdefghijklmnopqrstuv" not in red
    assert redact_secrets("password=hunter2hunter2") == "password=[REDACTED]"
    assert redact_secrets("nothing secret here") == "nothing secret here"
    store = TraceStore(tmp_path / "t.db")
    tr = Trace(query="use key gsk_abcdefghijklmnop1234 please")
    tr.add_step(TraceStep(StepType.TOOL_CALL, input={"api_key": "supersecretvalue99"}))
    tr.finish(result="token: ghp_abcdefghijklmnopqrstuvwxyz0123")
    store.save(tr)
    got = store.get(tr.trace_id)
    assert "gsk_abcdef" not in got.query and "supersecretvalue99" not in json.dumps(got.steps[0].input)
    assert "ghp_abcdef" not in got.result


def test_brain_logs_redacted_errors(caplog):
    b = make_brain()
    b.groq_client = fake_client(RuntimeError("bad key gsk_abcdefghijklmnop1234"))
    with caplog.at_level("WARNING", logger="Flexie.Brain"):
        b.ask("hello")
    assert "gsk_abcdefghijklmnop1234" not in caplog.text and "[REDACTED]" in caplog.text


def test_trace_store_wal_index_retention_and_no_n_plus_one(tmp_path):
    from core.traces import Trace, TraceAnalyzer, TraceStep, TraceStore
    from core.traces.trace import StepType

    path = tmp_path / "t.db"
    store = TraceStore(path)
    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    idx = [r[1] for r in store._conn.execute("PRAGMA index_list(trace_steps)")]
    assert "idx_trace_steps_trace" in idx
    old = Trace(query="old", started_at=time.time() - 40 * 86400)
    old.add_step(TraceStep(StepType.ROUTE))
    store.save(old)
    for i in range(12):
        t = Trace(query=f"q{i}")
        t.add_step(TraceStep(StepType.ROUTE))
        t.add_step(TraceStep(StepType.GENERATE))
        t.finish(outcome="success")
        store.save(t)
    store.close()
    store = TraceStore(path)                                       # startup retention (default 30 days)
    assert store.count() == 12 and store.get(old.trace_id) is None
    assert store._conn.execute("SELECT COUNT(*) FROM trace_steps WHERE trace_id=?", (old.trace_id,)).fetchone()[0] == 0
    queries = []
    store._conn.set_trace_callback(queries.append)
    traces = store.list_traces(limit=50)
    assert len(traces) == 12 and all(len(t.steps) == 2 for t in traces)
    assert len([q for q in queries if q.lstrip().upper().startswith("SELECT")]) == 2   # not 1 + N
    queries.clear()
    TraceAnalyzer(store).summary()
    assert len(queries) <= 3
    assert store.prune(0) == 0                                      # disabled


def test_telemetry_store_retention_index_and_wal(tmp_path):
    from core.telemetry.record import TelemetryRecord
    from core.telemetry.store import TelemetryStore

    path = tmp_path / "tel.db"
    s = TelemetryStore(path)
    s.record(TelemetryRecord(model_id="m", timestamp=time.time() - 40 * 86400))
    s.record(TelemetryRecord(model_id="m"))
    assert s.count() == 2
    s.close()
    s = TelemetryStore(path)
    assert s.count() == 1
    assert s._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert any(r[1] == "idx_telemetry_ts" for r in s._conn.execute("PRAGMA index_list(telemetry)"))
    assert TelemetryStore(path, retention_days=0).count() == 1


@pytest.fixture(autouse=True)
def _no_groq_sibling_models(monkeypatch):
    """These tests count calls to the single configured Groq model; sibling-model fallback
    (Config.GROQ_FALLBACK_MODELS) is covered in test_fix_projects_and_images.py."""
    from utils.config import Config
    monkeypatch.setattr(Config, "GROQ_FALLBACK_MODELS", (), raising=False)

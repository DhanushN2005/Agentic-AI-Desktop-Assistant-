"""Batch 1 audit fixes: brain fallback chain, DangerGate usage, route_dynamic guard."""
import json
from unittest.mock import MagicMock, patch

import core.brain as brain_mod
from core.brain import Brain
from core.router import IntentRouter


class FakeBrain:
    def __init__(self, text):
        self._text = text

    def ask(self, *a, **k):
        return self._text


def _make_brain_no_cloud():
    b = Brain.__new__(Brain)
    b.groq_client = None
    b.openai_client = None
    b.deepseek_client = None
    b.mistral_client = None
    b.anthropic_client = None
    b.gemini_new_client = None
    b.gemini_model = None
    b.gemini_chat = None
    b.provider_manager = None
    b.system_prompt = "sys"
    b.context_compiler = None
    b.vector_store = None
    b.memory_manager = None
    from collections import OrderedDict
    b._cache = OrderedDict()
    b._cache_max = 64
    return b


def test_no_duplicate_ask_ollama_and_ddg_exists():
    assert hasattr(Brain, "_ask_ollama")
    assert hasattr(Brain, "_ddg_search")
    assert hasattr(Brain, "_ask_ddg")
    # _ask_ddg must delegate to _ddg_search
    b = _make_brain_no_cloud()
    with patch.object(Brain, "_ddg_search", return_value="ddg-ok") as m:
        assert b._ask_ddg("hi") == "ddg-ok"
        m.assert_called_once_with("hi")


def test_ddg_search_friendly_fallback_without_package():
    b = _make_brain_no_cloud()
    with patch.object(brain_mod, "DDGS", None):
        out = b._ddg_search("quantum computing")
        assert isinstance(out, str) and len(out) > 10


def test_fallback_chain_ollama_then_ddg(monkeypatch):
    b = _make_brain_no_cloud()
    monkeypatch.setattr("core.brain.is_online", lambda: True)
    monkeypatch.setattr("utils.config.Config.ACTIVE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(Brain, "_ollama_reasoning", lambda self, *a, **k: None)
    monkeypatch.setattr(Brain, "_ask_ollama", lambda self, p: "ollama-answer")
    monkeypatch.setattr(Brain, "_ddg_search", lambda self, p: (_ for _ in ()).throw(AssertionError("should not reach DDG")))
    assert b.ask("hello world") == "ollama-answer"


def test_fallback_chain_reaches_ddg(monkeypatch):
    b = _make_brain_no_cloud()
    monkeypatch.setattr("core.brain.is_online", lambda: True)
    monkeypatch.setattr("utils.config.Config.ACTIVE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(Brain, "_ollama_reasoning", lambda self, *a, **k: None)
    monkeypatch.setattr(Brain, "_ask_ollama", lambda self, p: None)
    monkeypatch.setattr(Brain, "_ddg_search", lambda self, p: "ddg-fallback")
    assert b.ask("hello world") == "ddg-fallback"


def test_ollama_uses_config_url(monkeypatch):
    b = _make_brain_no_cloud()
    monkeypatch.setattr("utils.config.Config.OLLAMA_URL", "http://myhost:11434/api/generate", raising=False)
    assert b._ollama_base() == "http://myhost:11434"
    seen = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr("core.brain.urlopen", fake_urlopen)
    assert b._ollama_available() is True
    assert seen["url"] == "http://myhost:11434/api/tags"


def test_no_duckduckgo_search_import():
    import pathlib
    src = pathlib.Path("core/brain.py").read_text(encoding="utf-8")
    assert "duckduckgo_search" not in src


# --- DangerGate via developer engine ---
def test_developer_blocks_dangerous_command():
    from engines.developer import DeveloperEngine
    orch = MagicMock()
    orch.brain = MagicMock()
    orch.vision = MagicMock()
    orch.voice.confirm.return_value = False
    eng = DeveloperEngine(orch)
    out = eng.execute_terminal("please delete my account now")
    assert "cancelled" in out.lower()
    orch.voice.confirm.assert_called()


def test_developer_allows_safe_command():
    from engines.developer import DeveloperEngine
    orch = MagicMock()
    orch.brain = MagicMock()
    orch.brain.ask.return_value = "done"
    orch.vision = MagicMock()
    eng = DeveloperEngine(orch)
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = "hi"
    with patch("engines.developer.subprocess.run", return_value=fake) as r:
        out = eng.execute_terminal("echo hello")
        assert "hello" in out.lower() or "output" in out.lower()
        r.assert_called_once()


# --- route_dynamic ---
def test_route_dynamic_garbage_falls_back():
    r = IntentRouter()
    intent, conf, params = r.route_dynamic("open chrome", FakeBrain("garbage with no json at all"))
    assert intent == "app_op"  # falls back to normal route()
    assert isinstance(params, dict)


def test_route_dynamic_empty_falls_back():
    r = IntentRouter()
    intent, conf, params = r.route_dynamic("hello", FakeBrain(""))
    assert intent == "social"
    assert isinstance(params, dict)


def test_route_dynamic_none_falls_back():
    r = IntentRouter()
    intent, conf, params = r.route_dynamic("hello", FakeBrain(None))
    assert intent == "social"


def test_route_dynamic_valid_json():
    r = IntentRouter()
    payload = json.dumps({"intent": "search", "confidence": 0.9, "params": {"query": "cats"}})
    intent, conf, params = r.route_dynamic("search for cats", FakeBrain(payload))
    assert intent == "search"
    assert conf == 0.9
    assert params.get("query") == "cats"


def test_route_dynamic_invalid_json_falls_back():
    r = IntentRouter()
    intent, conf, params = r.route_dynamic("hello", FakeBrain("{not valid json"))
    assert intent == "social"

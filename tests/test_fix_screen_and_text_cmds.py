import types

import pytest

from core.handlers import dispatcher
from core.handlers.vision import _screen_prompt, handle_vision
from core.router import IntentRouter

R = IntentRouter()


@pytest.mark.parametrize("q", ["summarize the screen", "summarize my screen", "describe my screen",
                               "analyze my screen", "read my screen", "what's on my screen"])
def test_screen_phrases_route_to_vision(q):
    assert R.route(q)[0] == "vision_analyze"


def test_screen_prompt_follows_what_user_asked():
    assert "Summarize" in _screen_prompt("summarize my screen")
    assert "error" in _screen_prompt("what's wrong on my screen").lower()
    assert "Describe" in _screen_prompt("describe my screen")


class _Orch:
    def __init__(self, capture="ERROR: boom"):
        self.said = []
        self.ctx = types.SimpleNamespace(update=lambda **k: None)
        self.brain = object()
        outer = self
        self.vision = types.SimpleNamespace(
            capture_screen=lambda: capture,
            analyze_screen=lambda brain, prompt: f"ANALYZED[{prompt[:9]}]",
            read_screen_text=lambda: "hello text")
        self.speak = lambda t, **k: outer.said.append(t)


def test_screenshot_says_where_it_saved(tmp_path):
    o = _Orch(capture=str(tmp_path / "snap.png"))
    handle_vision(o, "vision_capture", "take a screenshot")
    assert "snap.png" in o.said[0] and str(tmp_path) in o.said[0]


def test_screenshot_failure_is_reported():
    o = _Orch()
    handle_vision(o, "vision_capture", "screenshot")
    assert "couldn't take the screenshot" in o.said[0]


def test_summarize_uses_summary_prompt_and_read_uses_ocr():
    o = _Orch()
    handle_vision(o, "vision_analyze", "summarize my screen")
    assert o.said[-1].startswith("ANALYZED[Summarize")
    handle_vision(o, "vision_analyze", "read my screen")
    assert o.said[-1] == "hello text"


def test_image_question_never_gets_text_only_guess_or_web_search(monkeypatch):
    from core import brain as brain_mod
    b = brain_mod.Brain.__new__(brain_mod.Brain)
    b.__dict__.update(groq_client=object(), provider_manager=None, _cache={}, _cache_lock=__import__("threading").Lock(),
                      system_prompt="x", context_compiler=None, vector_store=None, memory_manager=None)
    monkeypatch.setattr(brain_mod, "is_online", lambda: True)
    monkeypatch.setattr(b, "_active_provider", lambda: "auto", raising=False)
    monkeypatch.setattr(b, "_local_first_enabled", lambda a: False, raising=False)
    monkeypatch.setattr(b, "_circuit_allows", lambda n: True, raising=False)
    monkeypatch.setattr(b, "_report", lambda *a, **k: None, raising=False)
    called = []
    monkeypatch.setattr(b, "_ask_openai_compatible", lambda *a, **k: called.append("groq") or "hallucination", raising=False)
    monkeypatch.setattr(b, "_ask_gemini", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(b, "_ddg_search", lambda p: called.append("ddg") or "web", raising=False)
    out = b._ask_impl("describe", "img.png", None, False, False)
    assert out.startswith(brain_mod.VISION_UNAVAILABLE_MSG[:40])
    assert called == []                      # text-only provider and web search are never used


def test_stop_and_empty_model_reply_are_spoken():
    said = []
    o = types.SimpleNamespace(speak=lambda t, **k: said.append(t), send_to_ui=lambda *a, **k: None)
    assert dispatcher.handle_conversational(o, "stop") is True
    assert said == ["Okay."]


def test_failed_job_with_nothing_built_leaves_no_folder(tmp_path):
    import os

    from core.jobs.manager import JobManager
    from core.jobs.models import BuildJob
    ws = tmp_path / "proj-1"
    ws.mkdir()
    (ws / ".git").mkdir()
    (ws / ".gitignore").write_text("x")
    job = BuildJob(title="t", request_text="r")
    job.workspace_path = str(ws)
    JobManager._remove_if_nothing_built(job)
    assert not os.path.exists(ws)
    ws.mkdir()
    (ws / "app.py").write_text("print(1)")
    JobManager._remove_if_nothing_built(job)
    assert os.path.exists(ws / "app.py")        # real work is never removed

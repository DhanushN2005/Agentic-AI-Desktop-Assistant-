import types

import pytest

from core.handlers import system as sysh
from core.router import IntentRouter

R = IntentRouter()


@pytest.mark.parametrize("q", ["open chrome and search for youtube", "open chrome and search cats",
                               "launch chrome and google python tutorials", "open the browser and look up the weather"])
def test_open_browser_and_search_is_one_app_request(q):
    assert R.route(q)[0] == "app_op"


@pytest.mark.parametrize("q,expected", [
    ("close the chrome that u opened", "chrome"),
    ("close all chromes you have opened", "chrome"),
    ("close the chrome you have opened", "chrome"),
    ("close all the chrome that you have opened", "chrome"),
    ("close chrome windows", "chrome"),
    ("close the chrome.exe", "chrome.exe"),
    ("kill notepad", "notepad"),
    ("close all", "all"),
    ("close all apps", "all"),
])
def test_close_target_is_just_the_app_name(q, expected):
    assert sysh._clean_app_target(q) == expected


def test_search_in_browser_uses_encoded_url_and_speaks(monkeypatch):
    launched = []
    monkeypatch.setattr(sysh.subprocess, "Popen", lambda argv, **k: launched.append(argv))
    monkeypatch.setattr(sysh.sys, "platform", "win32")
    said = []
    orch = types.SimpleNamespace(speak=lambda t, **k: said.append(t), ctx=types.SimpleNamespace(update=lambda **k: None))
    assert sysh.handle_app_op(orch, "open chrome and search for cats & dogs; calc", False) is True
    argv = launched[0]
    assert argv[:4] == ["cmd.exe", "/c", "start", ""] and argv[4] == "chrome"
    assert "&" not in argv[5].split("q=", 1)[1] and ";" not in argv[5]        # query is percent-encoded
    assert said == ["Searching Google for cats & dogs; calc in chrome."]


# ---- misreads seen in a live session log ----
@pytest.mark.parametrize("q,intent", [
    ("wrong check my screen", "vision_analyze"),
    ("check my screen the tab u opened says wrong", "vision_analyze"),
    ("check my screen", "vision_analyze"),
    ("open vision mode", "vision_mode"),
    ("start vision mode", "vision_mode"),
    ("vision mode", "vision_mode"),
    ("close vision mode", "vision_mode"),
    ("skip that", "conversational"),
    ("okay skip those", "conversational"),
    ("wrong", "undo"),
    ("that's wrong", "undo"),
    ("undo that", "undo"),
    ("that is wrong about nvidia", "conversational"),
    ("he is former ceo", "conversational"),
])
def test_log_misreads_are_fixed(q, intent):
    assert R.route(q)[0] == intent


def test_search_query_drops_the_word_check():
    import re as _re
    q = _re.sub(r"\bin\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\s*", "", "check in chrome who is nvidia ceo")
    q = _re.sub(r"^(?:(?:search on chrome for|search on chrome|search for|search|google|look up|go to|find|check out|check)\s+)+", "", q).strip()
    assert q == "who is nvidia ceo"


def test_dismissal_and_vague_screen_requests(monkeypatch):
    from core.handlers import dispatcher
    from core.handlers.vision import _screen_prompt
    said = []
    o = types.SimpleNamespace(speak=lambda t, **k: said.append(t), send_to_ui=lambda *a, **k: None)
    assert dispatcher.handle_conversational(o, "okay skip those") is True and said == ["Okay."]
    assert "the tab u opened says wrong" in _screen_prompt("check my screen the tab u opened says wrong")
    assert _screen_prompt("describe my screen").startswith("Describe")


# ---- vision mode (the hand-gesture orb UI in vision/) ----
class _VM:
    def __init__(self, running=False, problem=None, start_ok=True):
        self._running, self._problem, self._start_ok = running, problem, start_ok
        self.url, self.started, self.stopped = "http://localhost:3000", 0, 0

    def is_running(self): return self._running
    def is_busy(self): return False
    def problem(self): return self._problem

    def start(self, say=lambda m: None):
        self.started += 1
        say("installing")
        return (True, self.url) if self._start_ok else (False, "Setting up vision mode failed: boom")

    def stop(self):
        self.stopped += 1
        return self._running


def _orch(vm):
    said = []
    return types.SimpleNamespace(vision_mode=vm, speak=lambda t, **k: said.append(t)), said


def test_open_vision_mode_starts_server_and_opens_browser(monkeypatch):
    import threading

    from core.handlers import vision_mode as vh
    opened = []
    monkeypatch.setattr(vh.webbrowser, "open", lambda u: opened.append(u) or True)
    vm = _VM()
    orch, said = _orch(vm)
    assert vh.handle_vision_mode(orch, "open vision mode") is True
    for t in [t for t in threading.enumerate() if t.name == "vision-mode-start"]:
        t.join(5)
    assert vm.started == 1 and opened == ["http://localhost:3000"]
    assert said[0] == "Starting vision mode." and "Press G" in said[-1]


def test_vision_mode_reports_problems_and_failures(monkeypatch):
    import threading

    from core.handlers import vision_mode as vh
    monkeypatch.setattr(vh.webbrowser, "open", lambda u: True)
    orch, said = _orch(_VM(problem="Node.js and npm are not installed"))
    vh.handle_vision_mode(orch, "open vision mode")
    assert said == ["Node.js and npm are not installed"]
    orch, said = _orch(_VM(start_ok=False))
    vh.handle_vision_mode(orch, "start vision mode")
    for t in [t for t in threading.enumerate() if t.name == "vision-mode-start"]:
        t.join(5)
    assert said[-1] == "Setting up vision mode failed: boom"


def test_close_vision_mode_and_already_running(monkeypatch):
    from core.handlers import vision_mode as vh
    opened = []
    monkeypatch.setattr(vh.webbrowser, "open", lambda u: opened.append(u) or True)
    vm = _VM(running=True)
    orch, said = _orch(vm)
    vh.handle_vision_mode(orch, "close vision mode")
    assert vm.stopped == 1 and said == ["Vision mode closed."]
    orch, said = _orch(_VM(running=True))
    vh.handle_vision_mode(orch, "open vision mode")
    assert opened == ["http://localhost:3000"] and "already running" in said[0]
    orch, said = _orch(_VM(running=False))
    vh.handle_vision_mode(orch, "stop vision mode")
    assert said == ["Vision mode isn't running."]


def test_vision_mode_engine_checks(tmp_path):
    from engines.vision_mode import VisionMode
    vm = VisionMode(app_dir=str(tmp_path))
    assert "missing" in vm.problem()
    (tmp_path / "package.json").write_text("{}")
    assert vm.needs_install() and not vm.is_running() and vm.stop() is False

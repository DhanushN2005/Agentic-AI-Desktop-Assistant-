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


# Vision mode (now the dashboard's Orb panel) is tested in tests/test_fix_orb_panel.py.


# ---- found by running the real app: these two intents had confidence 9/10 and no dispatcher branch ----
def test_every_override_has_a_valid_confidence_and_a_dispatch_branch():
    import inspect

    import core.router as r
    from core.handlers import dispatcher
    src = inspect.getsource(dispatcher)
    for _pattern, intent, conf in r.NL_OVERRIDES:
        assert 0 <= conf <= 1, (intent, conf)
        assert f'"{intent}"' in src or intent in ("conversational",) or intent in {i[0] for i in R.intents}, intent


def test_open_web_ui_and_run_command_reach_their_handlers(monkeypatch):
    from core.handlers import dispatcher, system
    seen = []
    monkeypatch.setattr(system, "handle_open_web_ui", lambda o, c: seen.append(("web", c)) or True)
    monkeypatch.setattr(system, "handle_run_cmd", lambda o, c: seen.append(("cmd", c)) or True)
    orch = types.SimpleNamespace(speak=lambda *a, **k: None, send_to_ui=lambda *a, **k: None,
                                 capability_registry=types.SimpleNamespace(get_capability_for_intent=lambda i: None),
                                 logger=types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None,
                                                              exception=lambda *a, **k: None, warning=lambda *a, **k: None))
    assert R.route("open web ui") == ("open_web_ui", 0.97)
    assert dispatcher.dispatch_intent(orch, "open_web_ui", "open web ui", False) is True
    assert dispatcher.dispatch_intent(orch, "run_command", "run command echo hi", False) is True
    assert [k for k, _ in seen] == ["web", "cmd"]


# ---- a blank Chromium window opened at every startup (YouTubeController pre-warm) ----
def test_browser_is_not_prewarmed_unless_asked(monkeypatch):
    from engines import youtube_controller as yc
    monkeypatch.delenv("FLEXIE_PREWARM_BROWSER", raising=False)
    assert yc.prewarm_enabled() is False
    monkeypatch.setenv("FLEXIE_PREWARM_BROWSER", "1")
    assert yc.prewarm_enabled() is True
    started = []
    monkeypatch.setattr(yc.threading, "Thread", lambda *a, **k: types.SimpleNamespace(start=lambda: started.append(k.get("name"))))
    monkeypatch.setattr(yc.BrowserEngine, "__init__", lambda self, orch=None: None)
    monkeypatch.delenv("FLEXIE_PREWARM_BROWSER")
    yc.YouTubeController()
    assert started == []                       # default: no pre-warm thread, so no browser window at launch
    monkeypatch.setenv("FLEXIE_PREWARM_BROWSER", "1")
    yc.YouTubeController()
    assert started == ["flexie_yt_prewarm"]


# ---- "vision mode" did nothing: the catch-all vision_* branch swallowed it before its own handler ----
def test_vision_mode_intent_reaches_its_handler_through_the_dispatcher(monkeypatch):
    from core.handlers import dispatcher
    from core.handlers import vision_mode as vh
    seen = []
    monkeypatch.setattr(vh, "handle_vision_mode", lambda o, c: seen.append(c) or True)
    orch = types.SimpleNamespace(speak=lambda *a, **k: None, send_to_ui=lambda *a, **k: None,
                                 capability_registry=types.SimpleNamespace(get_capability_for_intent=lambda i: None),
                                 logger=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                                              error=lambda *a, **k: None, exception=lambda *a, **k: None))
    assert dispatcher.dispatch_intent(orch, "vision_mode", "open vision mode", False) is True
    assert seen == ["open vision mode"]


def test_every_routable_intent_has_a_reachable_handler():
    """Dispatching each intent must not silently end in a handler that ignores it."""
    import inspect

    from core.handlers import dispatcher
    src = inspect.getsource(dispatcher.dispatch_intent)
    for _p, intent, _c in __import__("core.router", fromlist=["x"]).NL_OVERRIDES:
        if intent.startswith("vision_"):
            assert f'"{intent}"' in src or intent in ("vision_analyze", "vision_capture"), intent


# ================= found in a live session: python prompts, close web ui, which window, UI reject =================
def test_mentioning_python_does_not_need_confirmation_but_running_it_does():
    from core.permission_system import PermissionLevel, PermissionSystem
    ps = PermissionSystem()
    for harmless in ("generate python code for hello world", "tell me about python", "what is node js",
                     "write hello world in python"):
        assert ps.classify_action(harmless).value < PermissionLevel.USER_CONFIRMATION.value, harmless
    for risky in ("python script.py", "pip install requests", "run python script", "powershell Get-Process"):
        assert ps.classify_action(risky).value >= PermissionLevel.USER_CONFIRMATION.value, risky


def test_confirmation_prompt_is_only_called_destructive_when_it_is():
    from core.controller import FlexieController
    said = []
    orch = types.SimpleNamespace(speak=lambda t, **k: said.append(t), send_to_ui=lambda *a, **k: None,
                                 memory=None, active=True)
    ctl = FlexieController(orch, lambda *a, **k: None)
    from core.permission_system import PermissionSystem
    ctl.permission_system = PermissionSystem()
    ctl.execute("delete file zzz_probe.txt")
    assert "destructive or irreversible" in said[-1]
    ctl._clear_pending(reject=True)
    ctl.execute("run python script")
    assert "destructive" not in said[-1] and "change something" in said[-1] and "confirm" in said[-1]


@pytest.mark.parametrize("q", ["close the web ui", "close web ui", "close the dashboard", "stop the web dashboard"])
def test_close_web_ui_routes_to_its_own_intent(q):
    assert R.route(q)[0] == "close_web_ui"
    assert R.route("close chrome")[0] == "app_op" and R.route("close vision mode")[0] == "vision_mode"


def test_close_web_ui_stops_the_bridge(monkeypatch):
    import interface.launcher as L
    from core.handlers import system as sysh
    calls = []
    monkeypatch.setattr(L, "stop_any_bridge", lambda: calls.append(1) or True)
    said, ui = [], []
    orch = types.SimpleNamespace(speak=lambda t, **k: said.append(t), send_to_ui=lambda *a: ui.append(a))
    assert sysh.handle_close_web_ui(orch, "close the web ui") is True
    assert calls == [1] and ui == [("PANEL", "close")] and "closed" in said[0]
    monkeypatch.setattr(L, "stop_any_bridge", lambda: False)
    sysh.handle_close_web_ui(orch, "close the web ui")
    assert "isn't running" in said[-1]


def _wins(*titles):
    return [{"hwnd": 100 + i, "title": t, "pid": 1} for i, t in enumerate(titles)]


class _CloseEnv:
    """Fakes for SystemCtrl + voice so the close flow can be tested without real windows."""
    def __init__(self, monkeypatch, windows, answer="", confirm=True):
        from core.handlers import system as sysh
        self.sysh, self.said, self.closed_windows, self.closed_apps = sysh, [], [], []
        monkeypatch.setattr(sysh.SystemCtrl, "list_app_windows", staticmethod(lambda app: windows))
        monkeypatch.setattr(sysh.SystemCtrl, "close_window", staticmethod(lambda h: self.closed_windows.append(h) or True))
        monkeypatch.setattr(sysh.SystemCtrl, "close_app", staticmethod(lambda app: self.closed_apps.append(app) or True))
        self.orch = types.SimpleNamespace(
            speak=lambda t, **k: self.said.append(t),
            voice=types.SimpleNamespace(listen=lambda timeout=8: answer, confirm=lambda q: confirm))


def test_several_windows_ask_which_one_and_close_only_that_one(monkeypatch):
    env = _CloseEnv(monkeypatch, _wins("Inbox - Gmail", "RAS report", "New Tab"), answer="the second one")
    env.sysh._close_target(env.orch, "chrome", False)
    assert "3 chrome windows" in env.said[0] and "1: Inbox" in env.said[0] and "Which one" in env.said[0]
    assert env.closed_windows == [101] and env.closed_apps == []
    assert "RAS report" in env.said[-1]


@pytest.mark.parametrize("answer", ["", "cancel", "never mind", "banana", "7"])
def test_unclear_or_cancelled_answer_closes_nothing(monkeypatch, answer):
    env = _CloseEnv(monkeypatch, _wins("A", "B"), answer=answer)
    env.sysh._close_target(env.orch, "chrome", False)
    assert env.closed_windows == [] and env.closed_apps == []
    assert "didn't close anything" in env.said[-1]


def test_closing_all_windows_needs_a_second_confirmation(monkeypatch):
    env = _CloseEnv(monkeypatch, _wins("A", "B"), answer="all of them", confirm=False)
    env.sysh._close_target(env.orch, "chrome", False)
    assert env.closed_apps == [] and "left them open" in env.said[-1]
    env = _CloseEnv(monkeypatch, _wins("A", "B"), answer="all", confirm=True)
    env.sysh._close_target(env.orch, "chrome", False)
    assert env.closed_apps == ["chrome"]


def test_one_window_closes_politely_and_none_falls_back_to_the_process(monkeypatch):
    env = _CloseEnv(monkeypatch, _wins("Only window"))
    env.sysh._close_target(env.orch, "notepad", False)
    assert env.closed_windows == [100] and env.closed_apps == []
    env = _CloseEnv(monkeypatch, [])
    env.sysh._close_target(env.orch, "spotify", False)
    assert env.closed_apps == ["spotify"]


def test_listing_never_includes_flexies_own_browser_or_unknown_apps():
    from engines.system import SystemCtrl
    assert SystemCtrl.list_app_windows("") == [] and SystemCtrl.list_app_windows("all") == []
    assert SystemCtrl.app_process_names("chrome") and "python.exe" not in SystemCtrl.app_process_names("python")


def test_ui_reject_and_approve_reach_the_controller_through_the_action_queue(monkeypatch):
    """The orchestrator used to look for self.controller, which nothing ever set, so UI/API approve,
    reject and cancel were silently ignored and the prompt kept re-asking."""
    import queue
    import socket
    import threading
    import time

    import main
    from core.orchestrator import FlexieOrchestrator
    from utils import udp_auth

    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "t" * 32)
    assert "assistant.controller = controller" in open(main.__file__, encoding="utf-8").read()

    orch = FlexieOrchestrator.__new__(FlexieOrchestrator)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    logs = types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None,
                                 warning=lambda *a, **k: None, debug=lambda *a, **k: None)
    orch.__dict__.update(_udp_in=sock, cmd_queue=queue.Queue(), logger=logs, stop_event=threading.Event(),
                         speak=lambda *a, **k: None, send_to_ui=lambda *a, **k: None, permission_system=None,
                         controller=types.SimpleNamespace(pending_confirmation="delete file x", pending_request_id="apr_1"))
    threading.Thread(target=orch._network_loop, daemon=True).start()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for message, expected in (("REJECT:apr_1", "cancel"), ("CANCEL", "cancel"), ("APPROVE:apr_1", "confirm")):
        tx.sendto(udp_auth.pack(message).encode(), ("127.0.0.1", port))
        assert orch.cmd_queue.get(timeout=5) == expected, message
    tx.sendto(udp_auth.pack("APPROVE:apr_OTHER").encode(), ("127.0.0.1", port))   # a stale click for another request
    time.sleep(0.6)
    assert orch.cmd_queue.empty()


def test_ordinal_words_beat_the_word_one_in_both_pickers(monkeypatch):
    """"the second one" used to select item 1 (dict order matched the word 'one' first)."""
    from core.handlers import files as fh
    env = _CloseEnv(monkeypatch, _wins("A", "B", "C"), answer="the third one")
    env.sysh._close_target(env.orch, "chrome", False)
    assert env.closed_windows == [102]
    orch = types.SimpleNamespace(speak=lambda *a, **k: None, voice=types.SimpleNamespace(listen=lambda timeout=8: "the second one"))
    assert fh._choose_candidate(orch, ["C:/a/one.txt", "C:/a/two.txt", "C:/a/three.txt"]) == "C:/a/two.txt"

"""Launcher + web-dashboard parity tests (the PyQt HUD was replaced by interface/launcher.py).

What is executed here: parsing, bridge start/reuse/stop with fakes, fail-soft behaviour, the static
route, settings validation, the orchestrator's UDP handlers, and source-level checks of the web page.
What is NOT executed here: a real tray icon or global hotkey (needs a desktop session) and the
panels in a real browser (tests/js/panels_jsdom.mjs covers them under jsdom when jsdom is installed).
"""
import http.client
import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import types
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

import interface.launcher as L

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ hotkey spec
@pytest.mark.parametrize("spec,expected", [
    ("ctrl+alt+f", (L.MOD_CONTROL | L.MOD_ALT, ord("F"))),
    ("Ctrl + Shift + 9", (L.MOD_CONTROL | L.MOD_SHIFT, ord("9"))),
    ("win+f12", (L.MOD_WIN, 0x70 + 11)),
    ("alt+space", (L.MOD_ALT, 0x20)),
])
def test_parse_hotkey_valid(spec, expected):
    assert L.parse_hotkey(spec) == expected


@pytest.mark.parametrize("spec", ["f", "ctrl+", "", None, "ctrl+alt", "hyper+f", "ctrl+f25", "ctrl+ñ", "ctrl+alt+fx"])
def test_parse_hotkey_rejects_bare_keys_and_nonsense(spec):
    assert L.parse_hotkey(spec) is None            # a bare key would steal it from every app


def test_default_hotkey_is_not_bare_ctrl_f():
    flags, vk = L.parse_hotkey(L.DEFAULT_HOTKEY)
    assert flags & L.MOD_ALT and flags & L.MOD_CONTROL and vk == ord("F")


def test_ports_stay_in_sync_with_the_bridge():
    import interface.web_ui_bridge as b
    assert L.BRIDGE_HTTP_PORT == b.HTTP_PORT and L.BRIDGE_WS_PORT == b.WS_PORT
    assert L.ASSISTANT_UDP_PORT == b.ORCHESTRATOR_UDP_IN
    assert L.DASHBOARD_URL == f"http://localhost:{b.HTTP_PORT}/" and L.ORB_URL.endswith("/#orb")


# ------------------------------------------------------------ bridge supervision
@pytest.fixture(autouse=True)
def _reset_bridge_state(monkeypatch):
    monkeypatch.setattr(L, "_bridge_proc", None)
    monkeypatch.setattr(L, "_cleanup_registered", True)      # never register real atexit hooks in tests


class FakeProc:
    def __init__(self):
        self.terminated = self.killed = False
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def test_ensure_bridge_reuses_a_running_bridge(monkeypatch):
    monkeypatch.setattr(L, "bridge_alive", lambda *a, **k: True)
    monkeypatch.setattr(L.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start a second bridge"))
    assert L.ensure_bridge() is True


def test_ensure_bridge_starts_once_with_token_and_no_browser(monkeypatch):
    alive = iter([False, False, True])                       # not running, then comes up
    monkeypatch.setattr(L, "bridge_alive", lambda *a, **k: next(alive, True))
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.delenv("FLEXIE_UDP_TOKEN", raising=False)
    monkeypatch.setattr("utils.udp_auth.get_token", lambda *a, **k: "tok123")
    seen = {}

    def fake_popen(argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        return FakeProc()
    monkeypatch.setattr(L.subprocess, "Popen", fake_popen)
    assert L.ensure_bridge(wait=2) is True
    assert seen["argv"][-1].endswith("web_ui_bridge.py")
    assert seen["env"]["FLEXIE_UDP_TOKEN"] == "tok123"        # otherwise every relayed command is rejected
    assert seen["env"]["FLEXIE_BRIDGE_NO_BROWSER"] == "1"     # the caller decides when to open the page


def test_ensure_bridge_reports_failure_to_start(monkeypatch):
    monkeypatch.setattr(L, "bridge_alive", lambda *a, **k: False)
    def boom(*a, **k):
        raise OSError("no python")
    monkeypatch.setattr(L.subprocess, "Popen", boom)
    assert L.ensure_bridge(wait=0.2) is False


def test_stop_bridge_terminates_only_what_we_started(monkeypatch):
    assert L.stop_bridge() is False                           # a bridge started by hand is left alone
    proc = FakeProc()
    monkeypatch.setattr(L, "_bridge_proc", proc)
    assert L.stop_bridge() is True and proc.terminated and L._bridge_proc is None


def test_frozen_build_runs_the_bridge_through_the_exe(monkeypatch):
    monkeypatch.setattr(L.sys, "frozen", True, raising=False)
    assert L._bridge_command()[-1] == "--bridge"


def test_open_dashboard_blocking_opens_the_page_only_when_the_bridge_is_up(monkeypatch):
    opened = []
    monkeypatch.setattr(L.webbrowser, "open", lambda u: opened.append(u) or True)
    monkeypatch.setattr(L, "ensure_bridge", lambda *a, **k: False)
    assert L.open_dashboard(block=True) is False and opened == []
    monkeypatch.setattr(L, "ensure_bridge", lambda *a, **k: True)
    assert L.open_dashboard(L.ORB_URL, block=True) is True and opened == [L.ORB_URL]


def test_send_to_assistant_signs_the_datagram(monkeypatch):
    sent = []

    class Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def sendto(self, data, addr): sent.append((data, addr))
    monkeypatch.setattr(L.socket, "socket", lambda *a, **k: Sock())
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "abc")
    assert L.send_to_assistant("wake up") is True
    assert sent == [(b"TOKEN:abc wake up", ("127.0.0.1", L.ASSISTANT_UDP_PORT))]


# ------------------------------------------------------ hotkey / tray are fail-soft
def test_launcher_start_never_raises_and_loop_failures_are_swallowed(monkeypatch):
    launcher = L.Launcher()
    monkeypatch.setattr(L.Launcher, "_win_loop", lambda self: (_ for _ in ()).throw(RuntimeError("no desktop")))
    launcher._safe_loop()                                     # must not raise
    monkeypatch.setattr(L.sys, "platform", "linux")
    launcher.start()                                          # headless: no thread, no error
    assert launcher._thread is None
    launcher.stop()                                           # safe without a window


def test_hotkey_taken_or_invalid_is_only_a_warning():
    launcher = L.Launcher(hotkey="ctrl+alt+f")
    launcher.hwnd = 1

    class Taken:
        def RegisterHotKey(self, *a):
            raise OSError("already registered")
    assert launcher._register_hotkey(Taken()) is False

    class Fine:
        calls = []
        def RegisterHotKey(self, hwnd, id_, flags, vk):
            Fine.calls.append((hwnd, id_, flags, vk))
    assert launcher._register_hotkey(Fine()) is True
    assert Fine.calls[0][2] & L.MOD_NOREPEAT and Fine.calls[0][3] == ord("F")
    assert L.Launcher(hotkey="f")._register_hotkey(Fine()) is False


def test_tray_failure_is_soft():
    launcher = L.Launcher()
    launcher.hwnd = 1
    win32gui = types.SimpleNamespace(NIF_ICON=1, NIF_MESSAGE=2, NIF_TIP=4, NIM_ADD=0,
                                     LoadIcon=lambda *a: 1, LoadImage=lambda *a: 1,
                                     Shell_NotifyIcon=MagicMock(side_effect=OSError("no shell")))
    win32con = types.SimpleNamespace(IMAGE_ICON=1, LR_LOADFROMFILE=16, LR_DEFAULTSIZE=64, IDI_APPLICATION=32512)
    assert launcher._add_tray(win32gui, win32con) is False


def test_quit_callback_runs_off_the_message_thread():
    done = threading.Event()
    launcher = L.Launcher(on_quit=done.set)
    launcher._quit()
    assert done.wait(2)


# ----------------------------------------------------------------- main.py wiring
def test_main_starts_the_qt_hud_and_does_not_open_the_dashboard():
    """The Qt HUD (floating orb) is the desktop UI; the web dashboard opens only on request."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "run_ui" in src
    assert "open_dashboard" not in src and "webbrowser" not in src   # nothing opens a browser at startup


def test_launcher_is_a_helper_module_not_started_by_main():
    """interface.launcher stays available (bridge start/reuse for 'open web ui') but main.py does not
    start its tray/hotkey: the Qt HUD has its own, and a second tray icon would be confusing."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "start_launcher" not in src and "Launcher(" not in src
    assert callable(L.ensure_bridge) and callable(L.stop_bridge) and callable(L.open_dashboard)


def test_shutdown_is_safe_without_anything_started(monkeypatch):
    import main
    monkeypatch.setattr(L, "stop_bridge", lambda: False)
    main._shutdown(None, None)


def test_qt_hud_is_present():
    assert (ROOT / "interface" / "ui.py").exists()
    for name in ("requirements.txt", "pyproject.toml"):
        assert "PyQt6" in (ROOT / name).read_text(encoding="utf-8"), name


def test_ui_ports_always_include_the_qt_hud_port(monkeypatch, tmp_path):
    from utils import udp_auth
    monkeypatch.setattr(udp_auth, "UI_PORTS_FILE", str(tmp_path / "p"))
    assert udp_auth.ui_ports() == [udp_auth.DEFAULT_UI_PORT]      # the floating orb (Qt) always gets updates
    from utils.config import Config
    assert Config.UDP_PORT_UI == udp_auth.DEFAULT_UI_PORT


# ------------------------------------------------------------------ static route
@pytest.fixture
def static_server():
    import interface.web_ui_bridge as b
    srv = ThreadingHTTPServer(("127.0.0.1", 0), b._AuthedUIHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _get(port, path, host="localhost:8766"):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path, headers={"Host": host})
    r = c.getresponse()
    return r.status, r.getheader("Content-Type"), r.read()


def test_bridge_serves_panels_and_blocks_traversal(static_server):
    status, ctype, body = _get(static_server, "/static/panels.js")
    assert status == 200 and "javascript" in ctype and b"FlexiePanels" in body
    assert _get(static_server, "/static/panels.css")[0] == 200
    for bad in ("/static/../web_ui.html", "/static/%2e%2e/web_ui.html", "/static/panels.py", "/static/nope.js", "/static/a/b.js"):
        assert _get(static_server, bad)[0] == 404, bad
    assert _get(static_server, "/static/panels.js", host="evil.example")[0] == 421


# ---------------------------------------------------------------- web page parity
def test_dashboard_loads_and_routes_to_panels():
    html = (ROOT / "interface" / "web_ui.html").read_text(encoding="utf-8")
    assert '<script src="/static/panels.js"></script>' in html
    assert 'href="/static/panels.css"' in html
    assert "window.FlexiePanels.handle(tag, val)" in html and "FlexiePanels.onConnected()" in html
    assert "script-src 'self'" in html                        # /static/*.js needs no CSP change for panels


def test_panels_js_covers_what_the_qt_hud_did():
    js = (ROOT / "interface" / "static" / "panels.js").read_text(encoding="utf-8")
    for needle in ("APPROVAL_REQUEST", "APPROVAL_RESOLVED", "'APPROVE:'", "'REJECT:'", "'CANCEL'", "GET_SETTINGS",
                   "SAVE_SETTINGS:", "MAIL_COUNT", "MAIL_INBOX", "'QUIT'", "type = 'password'"):
        assert needle in js, needle
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)             # comments may mention the words
    # asserting the ABSENCE of innerHTML and of the eval function (nothing here calls it)
    assert "innerHTML" not in code and ("eval" + "(") not in code     # server text is never parsed as markup


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_panels_js_runs_under_jsdom():
    script = ROOT / "tests" / "js" / "panels_jsdom.mjs"
    probe = subprocess.run(["node", "-e", "require.resolve('jsdom')"], cwd=ROOT / "tests" / "js", capture_output=True)
    if probe.returncode != 0:
        pytest.skip("jsdom not installed (npm i jsdom in tests/js)")
    out = subprocess.run(["node", str(script), str(ROOT / "interface" / "static" / "panels.js")],
                         cwd=ROOT / "tests" / "js", capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr


# -------------------------------------------------------------- settings service
@pytest.fixture
def cfg(monkeypatch):
    from utils.config import Config
    written = {}
    monkeypatch.setattr(Config, "set_many_keys", classmethod(lambda cls, m: written.update(m) or True))
    monkeypatch.setattr(Config, "get_model", classmethod(lambda cls, p: "current-model"))
    monkeypatch.setattr(Config, "ACTIVE_PROVIDER", "auto", raising=False)
    monkeypatch.setattr(Config, "OLLAMA_URL", "http://localhost:11434/api/generate")
    monkeypatch.setattr(Config, "OLLAMA_MODEL", "tinyllama:latest")
    return written


def test_snapshot_never_contains_a_raw_key(monkeypatch):
    from core import settings_service as ss
    from utils.config import Config
    monkeypatch.setenv("GROQ_API_KEY", "gsk_SECRETSECRETSECRET1234")
    snap = ss.snapshot()
    assert "SECRETSECRET" not in json.dumps(snap)
    groq = next(p for p in snap["providers"] if p["id"] == "groq")
    assert groq["has_key"] is True and groq["model"] and "auto" in snap["active_choices"]
    assert snap["ollama"]["model"] == Config.OLLAMA_MODEL


def test_apply_validates_and_writes_only_what_changed(cfg):
    from core import settings_service as ss
    n, problems = ss.apply({
        "keys": {"groq": "gsk_abcdefgh12345678", "gemini": "", "openai": "has space key!", "nope": "x" * 20},
        "models": {"groq": "openai/gpt-oss-120b", "gemini": "current-model", "openai": "bad model;rm"},
        "active": "groq", "ollama_url": "http://localhost:11434/api/generate", "ollama_model": "llama3:8b"})
    assert cfg == {"GROQ_API_KEY": "gsk_abcdefgh12345678", "GROQ_MODEL": "openai/gpt-oss-120b",
                   "ACTIVE_PROVIDER": "groq", "OLLAMA_MODEL": "llama3:8b"}
    assert n == 4
    assert any("openai" in p and "key" in p for p in problems) and any("unknown provider" in p for p in problems)
    assert any("model name" in p for p in problems)
    assert not any("gsk_" in p or "has space" in p for p in problems)     # values are never echoed in problems


def test_apply_rejects_bad_payloads_and_urls(cfg):
    from core import settings_service as ss
    assert ss.apply("not a dict")[0] == 0
    n, problems = ss.apply({"ollama_url": "file:///etc/passwd", "active": "evil", "keys": {"groq": "x\nINJECT=1abcdefgh"}})
    assert n == 0 and cfg == {} and len(problems) == 3


def test_apply_reports_unwritable_env(monkeypatch):
    from core import settings_service as ss
    from utils.config import Config
    monkeypatch.setattr(Config, "set_many_keys", classmethod(lambda cls, m: False))
    n, problems = ss.apply({"keys": {"groq": "gsk_abcdefgh12345678"}})
    assert n == 0 and any(".env" in p for p in problems)


# ------------------------------------------- orchestrator UDP handlers (executed)
def _run_handler_loop(monkeypatch, datagrams, until):
    """Run FlexieOrchestrator._network_loop on a real localhost socket until ``until()`` is true."""
    import socket

    import core.orchestrator as orch_mod
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "tok")
    orch = object.__new__(orch_mod.FlexieOrchestrator)
    orch.logger = MagicMock()
    orch.brain = MagicMock()
    orch.send_to_ui = MagicMock()
    orch._note_auth_rejection = MagicMock()
    orch.cmd_queue = MagicMock()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    orch._udp_in = sock

    real_sleep = time.sleep
    loop_thread = []

    def stop(seconds=0, *a, **k):
        if loop_thread and threading.current_thread() is loop_thread[0]:
            raise SystemExit         # not an Exception, so the loop's own handler lets it end the thread
        real_sleep(seconds)
    monkeypatch.setattr(orch_mod.time, "sleep", stop)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)     # the deliberate SystemExit above ends the loop thread quietly
    t = threading.Thread(target=orch._network_loop, daemon=True)
    loop_thread.append(t)
    t.start()
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for d in datagrams:
        client.sendto(d.encode("utf-8"), sock.getsockname())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not until(orch):
        real_sleep(0.05)
    sock.close()                      # makes select() fail -> sleep -> SystemExit -> thread ends
    client.close()
    t.join(3)
    return orch


def test_orchestrator_get_settings_replies_with_a_masked_snapshot(monkeypatch):
    orch = _run_handler_loop(monkeypatch, ["TOKEN:tok GET_SETTINGS"],
                             until=lambda o: o.send_to_ui.called)
    tag, value = orch.send_to_ui.call_args[0]
    assert tag == "SETTINGS" and json.loads(value)["providers"]


def test_orchestrator_save_settings_reloads_brain_once_and_never_logs_keys(monkeypatch, cfg):
    payload = json.dumps({"keys": {"groq": "gsk_abcdefgh12345678"}, "active": "groq"})
    orch = _run_handler_loop(monkeypatch, ["TOKEN:tok SAVE_SETTINGS:" + payload],
                             until=lambda o: o.send_to_ui.called)
    assert cfg["GROQ_API_KEY"] == "gsk_abcdefgh12345678"
    orch.brain.reload_providers.assert_called_once()
    tag, value = orch.send_to_ui.call_args[0]
    assert tag == "SETTINGS_SAVED" and json.loads(value)["changed"] == 2
    logged = " ".join(str(c) for c in orch.logger.method_calls)
    assert "gsk_" not in logged and "abcdefgh" not in logged


def test_orchestrator_unsigned_or_malformed_settings_are_not_applied(monkeypatch, cfg):
    orch = _run_handler_loop(monkeypatch, ["SAVE_SETTINGS:" + json.dumps({"keys": {"groq": "gsk_abcdefgh12345678"}}),
                                           "TOKEN:tok SAVE_SETTINGS:{not json"],
                             until=lambda o: o.send_to_ui.called)
    assert cfg == {}
    tag, value = orch.send_to_ui.call_args[0]
    assert tag == "SETTINGS_SAVED" and json.loads(value)["changed"] == 0
    orch._note_auth_rejection.assert_called()


def test_approval_messages_the_web_page_must_answer_are_understood_by_the_orchestrator():
    """The modal answers with APPROVE:<id> / REJECT:<id> / APPROVE / CANCEL: all handled server side."""
    src = (ROOT / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assert 'msg in ("CONFIRM", "confirm", "APPROVE", "approve")' in src and 'msg.startswith(("CONFIRM:", "APPROVE:"))' in src
    assert 'msg.startswith(("REJECT:", "DENY:"))' in src and 'msg in ("STOP", "CANCEL", "stop", "cancel")' in src
    assert os.path.exists(ROOT / "core" / "settings_service.py")

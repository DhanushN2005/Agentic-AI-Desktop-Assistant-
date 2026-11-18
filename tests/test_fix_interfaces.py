"""Regression tests for the interface-layer fixes (UI-1 .. UI-23).

No GUI, microphone, browser or external network is used: the API runs under
FastAPI's TestClient, sockets/audio/subprocess are faked, JS is checked with
``node`` snippets (skipped when node is missing) or by reading the source.
"""
import asyncio
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
NODE = shutil.which("node")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _node(code: str) -> str:
    res = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


# ---------------------------------------------------------------- extension
def test_ui1_sidebar_has_no_duplicate_function_declarations():
    src = _read("extension", "sidebar.js")
    names = re.findall(r"^(?:async\s+)?function\s+(\w+)", src, flags=re.M)
    dups = {n for n in names if names.count(n) > 1}
    assert not dups, f"duplicate declarations: {dups}"
    # The mail wrapper must delegate to a DIFFERENT function (no self-recursion).
    assert "_origHandleDomCommand" not in src
    wrapper = src[src.index("async function handleDomCommand(raw)"):]
    assert "return handleDomCommandBase(raw);" in wrapper


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_ui1_sidebar_fallthrough_does_not_recurse():
    src = _read("extension", "sidebar.js")
    a = src.index("async function handleDomCommandBase")
    b = src.index("// ── Send handler")
    base = src[a:b]
    c = src.index("async function handleDomCommand(raw)")
    d = src.index("// ── Init")
    wrapper = src[c:d]
    code = (
        "let runDomTask=async()=>({ok:true}); let domTaskWithFeedback=async()=>true;"
        "let addSystemMsg=()=>{}; let addMessage=()=>{}; let sendMailCommand=async()=>{};"
        "let activeTab={id:1};"
        + base + wrapper +
        "handleDomCommand('what is the weather today').then(r=>console.log(String(r)))"
        ".catch(e=>console.log('ERR '+e.name));"
    )
    assert _node(code) in ("false", "true")  # i.e. not 'ERR RangeError'


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_ui12_call_api_endpoint_validation():
    src = _read("extension", "background.js")
    a = src.index("const ALLOWED_ENDPOINTS")
    b = src.index("// ── Message Router")
    cases = {
        "@evil.com/x": False, "//evil.com/x": False, "http://evil.com": False,
        "/health/../x": False, "/api/flexie/..%2fx": False, "/a\\b": False, "/unknown": False,
        "/health": True, "/command": True, "/api/flexie/mail/inbox?count=5": True,
        "/api/flexie/approve": True,
    }
    out = _node(
        "const chrome={};" + src[a:b] + ";const c=" + json.dumps(list(cases)) + ";"
        "console.log(JSON.stringify(c.map(e=>validateEndpoint(e)!==null)));"
    )
    assert json.loads(out) == list(cases.values())
    # sender hardening present
    assert "sender.id !== chrome.runtime.id" in src
    assert "PRIVILEGED_ENDPOINTS.some" in src and "sender.tab" in src


def test_ui13_context_menu_preserved_and_guarded():
    src = _read("extension", "background.js")
    assert re.search(r"try\s*{\s*const res = await chrome\.tabs\.sendMessage", src)
    assert "{ ...ctx, data:" in src                       # extracted data merged, not overwritten
    side = _read("extension", "sidebar.js")
    assert 'chrome.storage.local.get(["flexie_active_context"]' in side   # read once on load


def test_ui22_banner_uses_text_content():
    src = _read("extension", "content.js")
    block = src[src.index('type === "DOM_INJECT_BANNER"'):]
    block = block[:block.index("sendResponse({ ok: true })")]
    assert "innerHTML" not in block
    assert "request.message" in block and "append(" in block


@pytest.mark.skipif(not NODE, reason="node not installed")
@pytest.mark.parametrize("name", ["background.js", "content.js", "sidebar.js"])
def test_extension_js_syntax(name):
    res = subprocess.run([NODE, "--check", os.path.join(EXT, name)], capture_output=True, text=True, timeout=10)
    assert res.returncode == 0, res.stderr


def test_ui_sidebar_polling_stops_when_hidden():
    src = _read("extension", "sidebar.js")
    assert "visibilitychange" in src and "onActivated" in src
    assert ".slice(0, 4000)" in src            # client truncation matches the server's 4000 chars


# ------------------------------------------------------------------ web bridge
def _handler(host, path="/"):
    from interface.web_ui_bridge import _AuthedUIHandler
    h = object.__new__(_AuthedUIHandler)
    h.headers = {"Host": host} if host is not None else {}
    h.path = path
    h.sent = {"errors": [], "headers": [], "status": None}
    h.send_error = lambda code, *a, **k: h.sent["errors"].append(code)
    h.send_response = lambda code, *a, **k: h.sent.__setitem__("status", code)
    h.send_header = lambda k, v: h.sent["headers"].append((k, v))
    h.end_headers = lambda: None
    h.wfile = io.BytesIO()
    return h


@pytest.mark.parametrize("host", ["evil.example:8766", "localhost", "localhost:9999", "127.0.0.1:80", "", None])
def test_ui2_http_rejects_foreign_host(host):
    h = _handler(host)
    h.do_GET()
    assert h.sent["errors"] == [421]
    assert h.wfile.getvalue() == b""        # token page NOT served


@pytest.mark.parametrize("host", ["localhost:8766", "127.0.0.1:8766", "LOCALHOST:8766"])
def test_ui2_http_serves_allowed_host_without_cors(host):
    h = _handler(host)
    h.do_GET()
    assert h.sent["status"] == 200 and h.wfile.getvalue()
    assert not [k for k, _ in h.sent["headers"] if k.lower().startswith("access-control")]


def test_ui2_origin_allowlist():
    import interface.web_ui_bridge as b
    assert b._origin_allowed("http://localhost:8766")
    assert b._origin_allowed("http://127.0.0.1:8766")
    assert not b._origin_allowed("http://evil.com")
    assert not b._origin_allowed("null")
    assert not b._origin_allowed(None)                       # missing Origin, no token
    assert not b._origin_allowed(None, "wrong")
    assert b._origin_allowed(None, b.AUTH_TOKEN)             # non-browser client with token header
    assert not b._origin_allowed("http://evil.com", b.AUTH_TOKEN)   # browsers can't smuggle it


def _ws(headers):
    ws = MagicMock()
    ws.request = MagicMock(headers=headers)
    closed = {}

    async def close(code=1000, reason=""):
        closed["code"] = code
    ws.close = close
    ws.closed = closed
    return ws


def test_ui2_websocket_rejects_bad_origin_before_auth():
    import interface.web_ui_bridge as b
    ws = _ws({"Host": "localhost:8765", "Origin": "http://evil.com"})
    ws.recv = MagicMock(side_effect=AssertionError("must not even read a message"))
    asyncio.run(b.ws_handler(ws))
    assert ws.closed["code"] == 4003
    ws2 = _ws({"Host": "evil.com:8765", "Origin": "http://localhost:8766"})   # rebinding
    asyncio.run(b.ws_handler(ws2))
    assert ws2.closed["code"] == 4003


def test_ui9_bridge_udp_listener_drops_unsigned(monkeypatch):
    from utils import udp_auth
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "tok")
    monkeypatch.delenv("FLEXIE_ALLOW_UNSIGNED_UI", raising=False)
    assert udp_auth.decode_ui_datagram(b"QUIT:1") is None
    assert udp_auth.decode_ui_datagram(udp_auth.pack("STATE:IDLE").encode()) == "STATE:IDLE"


# ------------------------------------------------------------------ udp auth
def test_ui9_decode_ui_datagram(monkeypatch):
    from utils.udp_auth import decode_ui_datagram, pack
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "secret-token")
    monkeypatch.delenv("FLEXIE_ALLOW_UNSIGNED_UI", raising=False)
    assert decode_ui_datagram(pack("SAY:hello").encode()) == "SAY:hello"
    assert decode_ui_datagram(b"QUIT:x") is None                          # unsigned rejected
    assert decode_ui_datagram(b"TOKEN:wrong STATE:IDLE") is None          # forged token
    assert decode_ui_datagram(b"\xff\xfe\x00garbage") is None             # bad bytes: no exception
    assert decode_ui_datagram(b"") is None
    assert decode_ui_datagram(b"TOKEN:") is None
    monkeypatch.setenv("FLEXIE_ALLOW_UNSIGNED_UI", "1")
    assert decode_ui_datagram(b"STATE:IDLE") == "STATE:IDLE"              # migration flag
    assert "\ufffd" in decode_ui_datagram(b"SAY:\xff")                    # errors='replace'
    monkeypatch.setenv("FLEXIE_ALLOW_UNSIGNED_UI", "true")
    assert decode_ui_datagram(b"STATE:IDLE") is None                      # only exact "1"


def test_ui10_prefer_file_beats_stale_env(monkeypatch, tmp_path):
    from utils import udp_auth
    tokfile = tmp_path / "tok"
    tokfile.write_text("fresh-token")
    monkeypatch.setattr(udp_auth, "TOKEN_FILE", str(tokfile))
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "stale-env-token")
    assert udp_auth.get_token() == "stale-env-token"                       # default unchanged
    assert udp_auth.get_token(prefer_file=True) == "fresh-token"
    assert udp_auth.pack("X", prefer_file=True) == "TOKEN:fresh-token X"
    tokfile.unlink()
    assert udp_auth.get_token(prefer_file=True) == "stale-env-token"       # falls back to env


def test_ui10_bridge_signs_with_file_token(monkeypatch, tmp_path):
    import interface.web_ui_bridge as b
    from utils import udp_auth
    f = tmp_path / "tok"
    f.write_text("rotated")
    monkeypatch.setattr(udp_auth, "TOKEN_FILE", str(f))
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "stale")
    sent = []

    class FakeSock:
        def __init__(self, *a, **k): pass
        def sendto(self, data, addr): sent.append((data, addr))
        def close(self): pass
    monkeypatch.setattr(b.socket, "socket", FakeSock)
    assert b._send_udp("hello") is True
    assert sent[0][0] == b"TOKEN:rotated hello"


def test_ui11_ui_port_registry(monkeypatch, tmp_path):
    from utils import udp_auth
    monkeypatch.setattr(udp_auth, "UI_PORTS_FILE", str(tmp_path / "ports"))
    assert udp_auth.ui_ports() == [9886]
    udp_auth.register_ui_port(udp_auth.WEB_UI_PORT)
    udp_auth.register_ui_port(udp_auth.WEB_UI_PORT)         # idempotent
    assert udp_auth.ui_ports() == sorted({9886, udp_auth.WEB_UI_PORT})
    udp_auth.unregister_ui_port(udp_auth.WEB_UI_PORT)
    assert udp_auth.ui_ports() == [9886]
    udp_auth.register_ui_port(1234)
    udp_auth.reset_ui_ports()
    assert udp_auth.ui_ports() == [9886]
    (tmp_path / "ports").write_text("not json")
    assert udp_auth.ui_ports() == [9886]                    # corrupt registry never raises
    import interface.web_ui_bridge as b
    assert b.ORCHESTRATOR_UDP_OUT == udp_auth.WEB_UI_PORT != udp_auth.DEFAULT_UI_PORT


# ------------------------------------------------------------------ API server
@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from interface.api_server import create_app
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "t0k")
    orch = MagicMock()
    orch.active = True
    orch.cmd_queue = MagicMock()
    orch.cmd_queue.qsize.return_value = 0
    return TestClient(create_app(orch)), orch, {"Authorization": "Bearer t0k"}


@pytest.mark.parametrize("provider,expected_model", [("auto", ""), ("groq", None), ("ollama", None), ("bogus", "")])
def test_ui4_status_endpoint_works(api, monkeypatch, provider, expected_model):
    client, orch, h = api
    monkeypatch.setenv("ACTIVE_PROVIDER", provider)
    r = client.get("/api/flexie/status", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == provider
    if expected_model is not None:
        assert body["model"] == expected_model
    else:
        assert isinstance(body["model"], str)


def test_ui7_default_origins_dashboard_only(monkeypatch):
    from interface.api_server import _allowed_origins
    monkeypatch.delenv("FLEXIE_EXTRA_ORIGINS", raising=False)
    monkeypatch.delenv("FLEXIE_EXTENSION_IDS", raising=False)
    o = _allowed_origins()
    assert o == {"http://localhost:8766", "http://127.0.0.1:8766"}
    monkeypatch.setenv("FLEXIE_EXTRA_ORIGINS", "http://localhost:5173/, *, ftp://x, http://*.evil.com")
    o = _allowed_origins()
    assert "http://localhost:5173" in o and len(o) == 3        # '*', ftp and wildcard hosts rejected


def test_ui7_health_token_not_given_to_dev_ports(api):
    client, _, _ = api
    for origin in ("http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:8000"):
        assert "token" not in client.get("/health", headers={"Origin": origin}).json()
    assert client.get("/health", headers={"Origin": "http://localhost:8766"}).json()["token"] == "t0k"


def test_ui15_size_and_count_limits(api):
    client, orch, h = api
    assert client.post("/command", json={"command": "x" * 4001}, headers=h).status_code == 422
    assert client.post("/command", json={"command": "x" * 4000}, headers=h).status_code == 200
    big = {"query": "q" * 4001}
    assert client.post("/page-assist", json=big, headers=h).status_code == 422
    assert client.post("/page-assist", json={"query": "q", "selected_text": "s" * 20001}, headers=h).status_code == 422
    assert client.get("/api/flexie/mail/inbox?count=0", headers=h).status_code == 422
    assert client.get("/api/flexie/mail/inbox?count=51", headers=h).status_code == 422
    assert client.get("/api/flexie/mail/inbox?count=-3", headers=h).status_code == 422
    assert client.post("/api/flexie/mail/search", json={"query": "a", "count": 10**6}, headers=h).status_code == 422
    assert client.get("/api/flexie/usage?limit=100000", headers=h).status_code == 422


def test_ui15_command_queue_bounded(api):
    client, orch, h = api
    orch.cmd_queue.qsize.return_value = 50
    r = client.post("/command", json={"command": "hi"}, headers=h)
    assert r.status_code == 429
    orch.cmd_queue.put.assert_not_called()
    orch.cmd_queue.qsize.return_value = 49
    assert client.post("/command", json={"command": "hi"}, headers=h).status_code == 200


def test_ui15_approve_requires_request_id(api):
    client, orch, h = api
    orch.permission_system = MagicMock()
    for body in ({}, {"request_id": None}, {"request_id": ""}, {"request_id": "   "}):
        assert client.post("/api/flexie/approve", json=body, headers=h).status_code == 400
        assert client.post("/api/flexie/reject", json=body, headers=h).status_code == 400
    orch.permission_system.approve_request.assert_not_called()
    orch.permission_system.reject_request.assert_not_called()


def test_ui15_approve_unknown_id_is_404_and_handoff_via_queue(api):
    client, orch, h = api
    orch.permission_system = MagicMock()
    orch.permission_system.approve_request.return_value = False
    assert client.post("/api/flexie/approve", json={"request_id": "nope"}, headers=h).status_code == 404

    orch.permission_system.approve_request.return_value = True
    orch.controller = MagicMock()
    orch.controller.pending_confirmation = "delete x"
    r = client.post("/api/flexie/approve", json={"request_id": "apr_1"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    orch.controller._handle_confirmation.assert_not_called()        # not run on the request thread
    orch.cmd_queue.put.assert_called_with("confirm")

    orch.permission_system.reject_request.return_value = True
    client.post("/api/flexie/reject", json={"request_id": "apr_1"}, headers=h)
    orch.cmd_queue.put.assert_called_with("cancel")


def test_ui15_sse_connections_capped(api, monkeypatch):
    import interface.api_server as srv
    client, _, h = api
    monkeypatch.setattr(srv, "_sse_clients", srv.MAX_SSE_CLIENTS)
    assert client.get("/api/flexie/events", headers=h).status_code == 429


def test_ui15_page_assist_brain_is_cached(monkeypatch):
    import interface.api_server as srv
    built = []

    class FakeBrain:
        def __init__(self):
            built.append(1)

        def ask(self, *a, **k):
            return "ok"
    monkeypatch.setattr(srv, "_shared_brain", None)
    with patch.dict(sys.modules, {"core.brain": MagicMock(Brain=FakeBrain)}):
        a = srv._get_shared_brain()
        b = srv._get_shared_brain()
    assert a is b and len(built) == 1


def test_ui16_api_bind_failure_is_logged_at_error(caplog):
    import logging

    import interface.api_server as srv
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    try:
        with caplog.at_level(logging.ERROR, logger="Flexie.APIServer"):
            t = srv.start_api_server_background(port=port)
            t.join(timeout=5)
    finally:
        blocker.close()
    assert not t.is_alive()
    assert any(r.levelno >= logging.ERROR and "API server stopped" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ main.py
def test_ui16_single_instance_matches_full_path():
    import main
    here = os.path.dirname(main.__file__)
    assert main._cmdline_runs_main(["python", main.__file__])
    assert main._cmdline_runs_main(["python.exe", "main.py"], here)
    assert main._cmdline_runs_main(["C:/x/Flexie.exe"])
    assert not main._cmdline_runs_main(["python", "main.py"], os.path.join(here, "other_project"))
    assert not main._cmdline_runs_main(["python", "D:/proj/main.py"])
    assert not main._cmdline_runs_main(["python", "-m", "pytest", "domain.py"])
    assert not main._cmdline_runs_main([], here)
    assert not main._cmdline_runs_main(None, None)


def test_ui16_port_free_detection():
    import main
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        assert main._port_free("127.0.0.1", port) is False
    finally:
        s.close()
    assert main._port_free("127.0.0.1", port) is True


def test_ui16_shutdown_terminates_ui_even_if_cleanup_raises():
    import main
    ui = MagicMock()
    asst = MagicMock()
    asst.cleanup.side_effect = RuntimeError("boom")
    main._shutdown(asst, ui)
    ui.terminate.assert_called_once()
    main._shutdown(None, None)          # nothing started: must not raise


# ------------------------------------------------------------------ helpers
def test_ui17_is_online_uses_per_socket_timeout_and_cache(monkeypatch):
    import utils.helpers as helpers
    calls = []

    def fake_cc(target, timeout=None):
        calls.append((target, timeout))
        if target[0] == "1.1.1.1":
            return MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False)
        raise OSError("down")
    before = socket.getdefaulttimeout()
    monkeypatch.setattr(helpers.socket, "create_connection", fake_cc)
    monkeypatch.setitem(helpers._online_cache, "ts", 0.0)
    assert helpers.is_online() is True                     # one host up is enough
    assert socket.getdefaulttimeout() == before            # process-wide default untouched
    assert all(t == helpers._PROBE_TIMEOUT for _, t in calls) and len(calls) >= 1
    n = len(calls)
    assert helpers.is_online() is True and len(calls) == n  # cached (no new probes)


def test_ui17_is_online_false_when_all_probes_fail(monkeypatch):
    import utils.helpers as helpers

    def boom(target, timeout=None):
        raise OSError("down")
    monkeypatch.setattr(helpers.socket, "create_connection", boom)
    monkeypatch.setitem(helpers._online_cache, "ts", 0.0)
    t0 = time.monotonic()
    assert helpers.is_online() is False
    assert time.monotonic() - t0 < 2.0


# ------------------------------------------------------------------ path resolver
def test_ui18_path_resolver_keeps_filename_and_case(tmp_path):
    from pathlib import Path

    from utils.path_resolver import PathResolver
    r = PathResolver(workspace=str(tmp_path))
    home = Path.home()
    assert r.resolve("desktop/notes.txt") == str(home / "Desktop" / "notes.txt")
    assert r.resolve("Documents\\Reports\\Q1.PDF") == str(home / "Documents" / "Reports" / "Q1.PDF")
    assert r.resolve("Downloads folder") == str(home / "Downloads")
    assert r.resolve("my desktop") == str(home / "Desktop")
    assert r.resolve("in the downloads folder") == str(home / "Downloads")
    # alias only counts as the FIRST component
    assert r.resolve("project/desktop/Notes.txt") == os.path.join(str(tmp_path), "project/desktop/Notes.txt")
    assert r.resolve("Output/Result.py") == os.path.join(str(tmp_path), "Output/Result.py")   # case kept
    assert r.resolve("desktop/notes", default_extension=".txt").endswith("notes.txt")
    assert r.resolve("desktop", default_extension=".txt") == str(home / "Desktop")


# ------------------------------------------------------------------ preflight
def test_ui19_ollama_base_strips_api_path():
    from utils.preflight import _ollama_base
    assert _ollama_base("http://localhost:11434/api/generate") == "http://localhost:11434"
    assert _ollama_base("http://10.0.0.5:9000/") == "http://10.0.0.5:9000"
    assert _ollama_base("localhost:11434/api/generate") == "http://localhost:11434"
    assert _ollama_base("") == "http://localhost:11434"
    assert _ollama_base("https://h/ollama/api/generate") == "https://h"


def test_ui19_preflight_probes_tags_on_base_url(monkeypatch, tmp_path):
    from utils.preflight import _probe_ollama
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.full_url)
        raise OSError("refused")
    with patch("urllib.request.urlopen", fake_urlopen):
        res = _probe_ollama()
    assert seen == ["http://localhost:11434/api/tags"]
    assert res["ok"] is False and res["url"] == "http://localhost:11434"


def test_ui19_preflight_version_probe_is_cached(monkeypatch):
    import utils.preflight as pf
    monkeypatch.setattr(pf, "_version_cache", {})
    monkeypatch.setattr(pf.shutil, "which", lambda n: "C:/fake/tool.exe")
    runs = []

    def fake_run(cmd, **k):
        runs.append(cmd)
        return MagicMock(returncode=0, stdout="tool 1.2.3\n")
    monkeypatch.setattr(pf.subprocess, "run", fake_run)
    a = pf._check_binary("tool")
    b = pf._check_binary("tool")
    assert a["version"] == b["version"] == "tool 1.2.3" and len(runs) == 1


# ------------------------------------------------------------------ config
def test_ui20_env_never_overridden_by_dotenv():
    import ast
    tree = ast.parse(_read("utils", "config.py"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "load_dotenv":
            kw = {k.arg: getattr(k.value, "value", None) for k in node.keywords}
            assert kw.get("override") is False


def test_ui20_write_env_quotes_and_updates_environ(tmp_path, monkeypatch):
    import utils.config as cfg
    env = tmp_path / ".env"
    env.write_text("# keep me\nGROQ_MODEL=old\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "_env_path", lambda: str(env))
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert cfg._write_env_file({"GROQ_MODEL": "my model # not a comment"})
    assert cfg._write_env_file({"OLLAMA_MODEL": "plain:latest"})
    text = env.read_text(encoding="utf-8")
    assert "# keep me" in text and "OLLAMA_MODEL=plain:latest" in text
    assert 'GROQ_MODEL="my model # not a comment"' in text
    assert cfg._read_env_file()["GROQ_MODEL"] == "my model # not a comment"
    from dotenv import dotenv_values
    assert dotenv_values(str(env))["GROQ_MODEL"] == "my model # not a comment"
    assert os.environ["OLLAMA_MODEL"] == "plain:latest"       # settings UI keeps working w/o override
    for v in ('a"b', "it's", "back\\slash", "x y"):
        assert cfg._unquote_env_value(cfg._quote_env_value(v)) == v


def test_ui20_write_env_is_serialised(tmp_path, monkeypatch):
    import utils.config as cfg
    env = tmp_path / ".env"
    monkeypatch.setattr(cfg, "_env_path", lambda: str(env))
    errs = []

    def w(i):
        if not cfg._write_env_file({"GROQ_MODEL": f"m{i}", "OLLAMA_MODEL": f"o{i}"}):
            errs.append(i)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    data = cfg._read_env_file()
    assert data["GROQ_MODEL"][1:] == data["OLLAMA_MODEL"][1:]   # one writer's pair, never mixed/lost


def test_ui20_config_paths_and_bridge_key():
    from utils.config import Config
    from utils.paths import data_dir
    assert Config.JOB_BRIDGE_API_KEY not in ("", "flexie-local-bridge")
    for p in (Config.SNAP_PATH, Config.CAPTURE_DIR, Config.VECTOR_DB_PATH, Config.ARTIFACT_BACKUP_DIR):
        if not os.getenv("FLEXIE_ARTIFACT_BACKUP_DIR"):
            assert os.path.abspath(p).startswith(os.path.abspath(data_dir())), p


# ------------------------------------------------------------------ voice
def test_ui3_sapi_command_never_contains_text():
    from interface.voice import SAPI_TEXT_ENV, build_sapi_command
    nasty = "it's \u2019 \u2018 \u201a \u201b ; $(calc) `calc` \"x\" \n | & ' ; Remove-Item *"
    cmd = build_sapi_command(1, 100)
    joined = " ".join(cmd)
    assert nasty not in joined and "calc" not in joined and "Remove-Item" not in joined
    assert f"$synth.Speak($env:{SAPI_TEXT_ENV})" in joined
    # rate/volume are coerced, never interpolated raw
    evil = build_sapi_command("1; calc", "100'); calc; ('")
    assert "calc" not in " ".join(evil)
    assert "$synth.Rate = 0;" in " ".join(evil) and "$synth.Volume = 100;" in " ".join(evil)
    assert "$synth.Rate = 10;" in " ".join(build_sapi_command(99, -5)) and "$synth.Volume = 0;" in " ".join(build_sapi_command(99, -5))


@pytest.mark.parametrize("text", [
    "plain", "it's", "curly \u2019 quote", "\u2018a\u2019 \u201a \u201b", "a; b", "$(whoami)", "`id`",
    "line1\nline2", "'; Remove-Item C:\\ -Recurse; '", "",
])
def test_ui3_sapi_text_passes_via_env_only(monkeypatch, text):
    import interface.voice as vm
    captured = {}

    class FakeProc:
        def poll(self): return 0
        def terminate(self): pass
        def wait(self, timeout=None): return 0

    def fake_popen(argv, **kw):
        captured["argv"], captured["env"] = argv, kw.get("env", {})
        return FakeProc()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
    v = object.__new__(vm.VoiceInterface)
    v.speech_rate, v.speech_volume = 1, 100
    v._active_speech_proc = None
    assert v._speak_sapi(text) == vm.SpeakResult.SPOKEN
    assert captured["env"][vm.SAPI_TEXT_ENV] == text
    for arg in captured["argv"]:
        assert text not in arg or text == ""


def _worker_voice(vm, monkeypatch, neural, sapi):
    import queue
    monkeypatch.setattr(vm, "is_online", lambda: True)
    v = object.__new__(vm.VoiceInterface)
    v.speech_queue = queue.Queue()
    v.stop_speech = False
    v.is_speaking = False
    v.speech_mode = "neural"
    v._neural_disabled = False
    v._neural_fail_count = 0
    v._speak_end_time = 0
    v.last_spoken_text = None
    v.last_spoken_time = 0
    v._speech_buffer = ""
    v._active_speech_proc = None
    v._speak_neural = neural
    v._speak_sapi = sapi
    t = threading.Thread(target=v._speech_worker, daemon=True)
    t.start()
    return v, t


def _drain(v, t):
    assert _wait(lambda: v.speech_queue.unfinished_tasks == 0)
    v.stop_speech = True
    t.join(timeout=3)


def _wait(cond, timeout=2.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_ui5_interrupted_neural_does_not_fall_back_or_count(monkeypatch):
    import interface.voice as vm
    sapi_calls, neural_calls = [], []

    def neural(text):
        neural_calls.append(text)
        return vm.SpeakResult.INTERRUPTED
    v, t = _worker_voice(vm, monkeypatch, neural, lambda text: sapi_calls.append(text) or vm.SpeakResult.SPOKEN)
    for i in range(5):                                   # user stops 5 times
        v.speak(f"Sentence number {i}.")
        assert _wait(lambda n=i: len(neural_calls) == n + 1)
        time.sleep(0.05)
    _drain(v, t)
    assert sapi_calls == []                              # never replayed in SAPI
    assert v._neural_fail_count == 0 and v._neural_disabled is False


def test_ui5_real_failure_falls_back_and_disables_after_three(monkeypatch):
    import interface.voice as vm
    sapi_calls = []
    v, t = _worker_voice(vm, monkeypatch, lambda text: vm.SpeakResult.FAILED,
                         lambda text: sapi_calls.append(text) or vm.SpeakResult.SPOKEN)
    for i in range(3):
        v.speak(f"Failure number {i}.")
        assert _wait(lambda n=i: len(sapi_calls) == n + 1)
        time.sleep(0.05)
    _drain(v, t)
    assert len(sapi_calls) == 3 and v._neural_disabled is True


def test_ui6_interrupt_does_not_drop_the_new_reply(monkeypatch):
    import interface.voice as vm
    spoken = []
    v, t = _worker_voice(vm, monkeypatch, lambda text: spoken.append(text) or vm.SpeakResult.SPOKEN,
                         lambda text: vm.SpeakResult.SPOKEN)
    v.stop()                                             # leaves the interrupt flag set while idle
    v.speak("Brand new reply.", interrupt=True)
    assert _wait(lambda: spoken == ["Brand new reply."])
    v.speak("Old reply one. Old reply two. Old reply three.")
    v.stop()                                             # drops everything queued before it
    v.speak("Fresh answer.", interrupt=True)
    assert _wait(lambda: "Fresh answer." in spoken)
    _drain(v, t)
    assert spoken[-1] == "Fresh answer."


def test_ui6_stale_generation_items_are_discarded(monkeypatch):
    import interface.voice as vm
    spoken = []
    v, t = _worker_voice(vm, monkeypatch, lambda text: spoken.append(text) or vm.SpeakResult.SPOKEN,
                         lambda text: vm.SpeakResult.SPOKEN)
    v.speech_queue.put((v._gen - 1, "stale"))
    v.speech_queue.put((v._gen, "current"))
    _drain(v, t)
    assert spoken == ["current"]


def test_ui21_duplicate_suppressed_only_while_active(monkeypatch):
    import queue

    import interface.voice as vm
    v = object.__new__(vm.VoiceInterface)
    v.speech_queue = queue.Queue()
    v.is_speaking = False
    v.last_spoken_text = None
    v.last_spoken_time = 0
    v._speech_buffer = ""
    v.speak("Opening Chrome.")
    assert v.speech_queue.qsize() == 1
    v.speak("Opening Chrome.")                           # still queued -> suppressed
    assert v.speech_queue.qsize() == 1
    v.speech_queue.get_nowait()                          # finished speaking
    v.speak("Opening Chrome.")                           # user repeated the command -> spoken again
    assert v.speech_queue.qsize() == 1


def test_ui21_speech_buffer_lock_exists_and_empty_after_speak():
    import queue

    import interface.voice as vm
    v = object.__new__(vm.VoiceInterface)
    v.speech_queue = queue.Queue()
    v.is_speaking = False
    v.last_spoken_text = None
    v.last_spoken_time = 0
    v._speech_buffer = ""
    errs = []

    def go(i):
        try:
            v.speak(f"Thread {i} says one. Thread {i} says two. Thread {i} says three.")
        except Exception as e:  # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and v._speech_buffer == ""
    texts = []
    while not v.speech_queue.empty():
        texts.append(v.speech_queue.get_nowait()[1])
    assert all(re.fullmatch(r"(Thread (\d) says \w+\.\s?)+", x) for x in texts)
    assert len(re.findall(r"says", " ".join(texts))) == 18   # nothing lost


def test_ui21_confirm_times_out_when_worker_died(monkeypatch):
    import queue

    import interface.voice as vm
    v = object.__new__(vm.VoiceInterface)
    v.speech_queue = queue.Queue()
    v.speech_queue.put((0, "never spoken"))              # nobody will ever drain this
    v.is_speaking = True
    v.last_spoken_text = None
    v.last_spoken_time = 0
    v._speech_buffer = ""
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    v.speech_thread = dead
    monkeypatch.setattr(v, "listen", lambda timeout=None: "")
    t0 = time.monotonic()
    assert v.confirm("Are you sure?") is False
    assert time.monotonic() - t0 < 2.0


def test_ui14_google_asr_gets_operation_timeout(monkeypatch):
    from test_voice_vad import frame, make_voice, silence_frame

    import interface.voice as vm
    seen = {}

    class Rec:
        energy_threshold = 300.0
        pause_threshold = 0.8
        non_speaking_duration = 0.4

        def recognize_google(self, audio, language=None):
            seen["timeout"] = self.operation_timeout
            return "Hello"
    monkeypatch.setattr(vm, "is_online", lambda: True)
    frames = [silence_frame() for _ in range(10)] + [frame(1500) for _ in range(40)]
    v = make_voice(frames, tail=silence_frame())
    v.recognizer = Rec()
    assert v.listen_adaptive(mode="normal") == "hello"
    assert seen["timeout"] == 8


def test_ui14_asr_lock_released_after_timeout(monkeypatch):
    from test_voice_vad import frame, make_voice, silence_frame

    import interface.voice as vm

    class Rec:
        energy_threshold = 300.0
        pause_threshold = 0.8
        non_speaking_duration = 0.4

        def recognize_google(self, audio, language=None):
            raise TimeoutError("timed out")
    monkeypatch.setattr(vm, "is_online", lambda: True)
    frames = [silence_frame() for _ in range(10)] + [frame(1500) for _ in range(40)]
    v = make_voice(frames, tail=silence_frame())
    v.recognizer = Rec()
    v.listen_adaptive(mode="normal")                       # falls back to offline stub
    assert v._asr_lock.acquire(blocking=False)             # lock was released
    v._asr_lock.release()


def test_ui_send_to_ui_reuses_one_signed_socket(monkeypatch):
    import interface.voice as vm
    made, sent = [], []

    class FakeSock:
        def __init__(self, *a, **k): made.append(self)
        def sendto(self, data, addr): sent.append((data, addr))
    monkeypatch.setattr(vm.socket, "socket", FakeSock)
    monkeypatch.setattr(vm.VoiceInterface, "_udp_sock", None)
    monkeypatch.setattr(vm.VoiceInterface, "_ui_ports_cache", ([9886, 9888], time.monotonic()))
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "tk")
    v = object.__new__(vm.VoiceInterface)
    v.send_to_ui("STATE", "LISTENING")
    v.send_to_ui("PARTIAL", "hi")
    assert len(made) == 1                                   # one socket for all sends
    assert [a[1] for _, a in [(d, a) for d, a in sent]] == [9886, 9888, 9886, 9888]   # fan-out
    assert sent[0][0] == b"TOKEN:tk STATE:LISTENING"        # signed


def test_ui_listening_partial_is_throttled(monkeypatch):
    from test_voice_vad import frame, make_voice, silence_frame

    import interface.voice as vm
    monkeypatch.setattr(vm, "is_online", lambda: False)
    frames = [silence_frame() for _ in range(5)] + [frame(1500) for _ in range(30)]
    v = make_voice(frames, tail=silence_frame())
    v._last_partial_sent = ""
    v.listen_adaptive(mode="normal")
    listening = [x for x in v.sent_ui if x == ("PARTIAL", "Listening...")]
    assert len(listening) == 1                               # state change only, not every frame


def test_ui_fast_rms_matches_reference():
    import math
    import random
    import struct

    from interface.voice import _frame_rms_peak
    rnd = random.Random(1)
    shorts = [rnd.randint(-32768, 32767) for _ in range(480)]
    raw = struct.pack("480h", *shorts)
    rms, peak = _frame_rms_peak(raw, 480)
    assert rms == pytest.approx(math.sqrt(sum(float(s) ** 2 for s in shorts) / 480), rel=1e-3)
    assert peak == max(max(shorts), -min(shorts)) or peak == 32768 or peak == max(abs(s) for s in shorts)


def test_ui_voice_init_has_no_pyttsx3_enumeration_and_background_mic():
    src = _read("interface", "voice.py")
    assert "pyttsx3.init" not in src
    assert "_init_mic_background" in src and "adjust_for_ambient_noise" in src
    init = src[src.index("def __init__"):src.index("def _init_mic_background")]
    assert "adjust_for_ambient_noise" not in init            # not on the startup path


# ------------------------------------------------------------------ dashboard html
def test_ui8_toast_and_mcp_do_not_use_innerhtml():
    html = _read("interface", "web_ui.html")
    for fn in ("function toast(", "function handleMCP("):
        body = html[html.index(fn):]
        body = body[:body.index("\n}\n")]
        assert "innerHTML" not in body, fn
        assert "textContent" in body
    assert "&quot;" in html and "&#39;" in html            # _escape handles quotes too


def test_ui23_csp_and_sri_present():
    html = _read("interface", "web_ui.html")
    assert 'http-equiv="Content-Security-Policy"' in html
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
    assert "object-src 'none'" in csp and "default-src 'none'" in csp
    assert "connect-src ws://localhost:8765" in csp
    link = re.search(r'<link[^>]+font-awesome[^>]+>', html).group(0)
    assert 'integrity="sha512-' in link and 'crossorigin="anonymous"' in link

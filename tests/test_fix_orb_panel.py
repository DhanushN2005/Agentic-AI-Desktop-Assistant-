"""The orb is a panel of the web dashboard (interface/static/orb*.js), and "open vision mode" opens it."""
import http.client
import os
import re
import threading
import types
from http.server import ThreadingHTTPServer

import pytest

import interface.web_ui_bridge as bridge
from core.router import IntentRouter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "interface", "static")
HTML = os.path.join(ROOT, "interface", "web_ui.html")


# ---------------------------------------------------------------- static files served by the bridge
@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), bridge._AuthedUIHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _get(port, path, host="localhost:8766"):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", path, headers={"Host": host})
    r = c.getresponse()
    return r.status, r.getheader("Content-Type"), r.getheader("X-Content-Type-Options"), r.read()


def test_bridge_serves_orb_bundle_same_origin_with_nosniff(server):
    status, ctype, nosniff, body = _get(server, "/static/orb.js")
    assert status == 200 and ctype.startswith("text/javascript") and nosniff == "nosniff"
    assert b"FlexieOrb" in body
    assert _get(server, "/static/orb.css")[1].startswith("text/css")
    assert _get(server, "/static/orb-panel.js")[0] == 200


@pytest.mark.parametrize("path", ["/static/../web_ui.html", "/static/%2e%2e/web_ui.html", "/static/sub/orb.js",
                                  "/static/orb.py", "/static/nope.js", "/static/", "/static/.env"])
def test_bridge_static_route_rejects_traversal_unknown_types_and_missing(server, path):
    assert _get(server, path)[0] == 404


def test_bridge_static_route_keeps_the_host_check(server):
    assert _get(server, "/static/orb.js", host="evil.example.com")[0] == 421


# ---------------------------------------------------------------- built bundle
def test_bundle_files_exist_and_expose_the_api():
    orb = open(os.path.join(STATIC, "orb.js"), encoding="utf-8").read()
    for name in ("mount", "setState", "setGestures", "destroy"):
        assert name in orb
    assert "FlexieOrb" in orb
    gest = open(os.path.join(STATIC, "orb-gestures.js"), encoding="utf-8").read()
    assert "FlexieOrbGestures" in gest
    # MediaPipe lives only in the lazily loaded bundle, never in the dashboard-load bundle
    assert "hand_landmarker" in gest and "hand_landmarker" not in orb


def test_gestures_are_off_by_default_and_never_load_with_the_scene():
    src = open(os.path.join(ROOT, "interface", "orb", "src", "entry.ts"), encoding="utf-8").read()
    assert "orb-gestures.js" in src and "getUserMedia" not in src      # camera is only touched inside HandTracker.start
    assert 'GESTURES OFF' in src


# ---------------------------------------------------------------- dashboard wiring + CSP
def test_dashboard_loads_the_orb_panel_and_forwards_messages():
    html = open(HTML, encoding="utf-8").read()
    assert '/static/orb-panel.js' in html and '/static/orb.css' in html
    assert "FlexieOrbPanel.onMessage(tag, val)" in html
    assert "FlexieOrbPanel.onConnection(online)" in html
    panel = open(os.path.join(STATIC, "orb-panel.js"), encoding="utf-8").read()
    assert "PANEL" in panel and "#orb" in panel and "window.send" in panel


def test_csp_only_adds_what_hand_gestures_need():
    html = open(HTML, encoding="utf-8").read()
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
    directives = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in csp.split(";")) if d}
    assert directives["default-src"] == ["'none'"]
    assert set(directives["script-src"]) == {"'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "'wasm-unsafe-eval'"}
    assert {"https://cdn.jsdelivr.net", "https://storage.googleapis.com"} <= set(directives["connect-src"])
    assert directives["worker-src"] == ["blob:"]
    allowed_hosts = set(re.findall(r"https://[\w.-]+", csp))
    assert allowed_hosts <= {"https://cdn.jsdelivr.net", "https://storage.googleapis.com", "https://cdnjs.cloudflare.com",
                             "https://fonts.googleapis.com", "https://fonts.gstatic.com"}
    assert directives["object-src"] == ["'none'"] and directives["form-action"] == ["'none'"]


# ---------------------------------------------------------------- vision mode handler
@pytest.mark.parametrize("q", ["open vision mode", "start vision mode", "vision mode", "start the orb", "close vision mode"])
def test_vision_mode_phrases_still_route_to_vision_mode(q):
    assert IntentRouter().route(q)[0] == "vision_mode"


class _VM:
    def __init__(self, problem=None):
        self._problem = problem
        self.url = "http://localhost:8766/#orb"

    def problem(self):
        return self._problem


def _orch(vm):
    said, ui = [], []
    orch = types.SimpleNamespace(vision_mode=vm, speak=lambda t, **k: said.append(t),
                                 send_to_ui=lambda tag, val: ui.append((tag, val)))
    return orch, said, ui


def test_open_vision_mode_starts_bridge_if_needed_and_opens_the_orb_tab(monkeypatch):
    from core.handlers import system as sysh
    from core.handlers import vision_mode as vh
    opened, ensured = [], []
    monkeypatch.setattr(sysh, "ensure_web_bridge", lambda orch: ensured.append(1) or True)
    monkeypatch.setattr(vh.webbrowser, "open", lambda u: opened.append(u) or True)
    orch, said, ui = _orch(_VM())
    assert vh.handle_vision_mode(orch, "open vision mode") is True
    assert ensured == [1] and opened == ["http://localhost:8766/#orb"]
    assert ui == [("PANEL", "orb")] and "Press G" in said[-1]


def test_open_vision_mode_reports_a_bridge_that_would_not_start(monkeypatch):
    from core.handlers import system as sysh
    from core.handlers import vision_mode as vh
    opened = []
    monkeypatch.setattr(sysh, "ensure_web_bridge", lambda orch: False)
    monkeypatch.setattr(vh.webbrowser, "open", lambda u: opened.append(u) or True)
    orch, said, ui = _orch(_VM())
    vh.handle_vision_mode(orch, "start vision mode")
    assert opened == [] and "couldn't start the web UI bridge" in said[-1]


def test_open_vision_mode_reports_missing_bundle(monkeypatch):
    from core.handlers import vision_mode as vh
    monkeypatch.setattr(vh.webbrowser, "open", lambda u: pytest.fail("must not open a browser"))
    orch, said, ui = _orch(_VM(problem="The orb files are missing (orb.js)."))
    vh.handle_vision_mode(orch, "open vision mode")
    assert said == ["The orb files are missing (orb.js)."] and ui == []


def test_close_vision_mode_sends_panel_close_and_kills_nothing(monkeypatch):
    from core.handlers import vision_mode as vh
    orch, said, ui = _orch(_VM())
    vh.handle_vision_mode(orch, "close vision mode")
    assert ui == [("PANEL", "close")] and said == ["Vision mode closed."]


def test_engine_reports_missing_files(tmp_path):
    from engines.vision_mode import VisionMode
    vm = VisionMode(static_dir=str(tmp_path))
    assert "orb.js" in vm.problem() and "npm run build" in vm.problem()
    for f in ("orb.js", "orb.css", "orb-panel.js"):
        (tmp_path / f).write_text("x")
    assert vm.problem() is None and vm.url.endswith("#orb")
    assert VisionMode().problem() is None            # the committed bundle is present


def test_no_npm_or_dev_server_code_remains_in_vision_mode():
    for rel in ("engines/vision_mode.py", "core/handlers/vision_mode.py"):
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for word in ("npm", "subprocess", "atexit", "Popen"):
            assert word not in src.replace("npm install && npm run build", ""), (rel, word)


def test_hud_orb_is_an_opt_in_subclass_that_paints_every_state():
    import os
    import pathlib
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    src = pathlib.Path(__file__).resolve().parents[1] / "interface"
    ui = (src / "ui.py").read_text(encoding="utf-8")
    assert 'os.environ.get("FLEXIE_ORB_STYLE"' in ui and "class EnhancedFlexieOrb" in ui   # classic kept and default
    assert not (src / "orb_v3.py").exists()
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from interface.orb_v2 import HudFlexieOrb
    orb = HudFlexieOrb()
    orb.timer.stop()
    pm = QPixmap(300, 300)
    for mode in ("professional", "hacker", "minimal"):
        orb.mode = mode
        for state in ("IDLE", "LISTENING", "PROCESSING", "SPEAKING", "SLEEP", "ERROR"):
            orb.set_state(state)
            orb._view_scale = 1.0
            orb.render(pm)          # an exception inside paintEvent would abort the process
    assert app is not None


def test_black_hole_orb_is_opt_in_and_keeps_the_orb_api():
    import pathlib
    static = pathlib.Path(__file__).resolve().parents[1] / "interface" / "static"
    bh = (static / "orb-blackhole.js").read_text(encoding="utf-8")
    for api in ("mount:", "destroy:", "setState:", "setSpeech:", "setConnected:", "setGestures:"):
        assert api in bh, api                                   # same surface as the classic orb.js
    assert "offsetParent" not in bh.replace("offsetParent is null", "")   # fixed overlays have a null offsetParent
    panel = (static / "orb-panel.js").read_text(encoding="utf-8")
    assert "orb-blackhole.js" in panel and "'/static/orb.js'" in panel and "?orb=blackhole" in panel
    assert (static / "orb.js").exists()                          # the classic orb is still there and still the default
    assert all(ord(c) < 128 for c in bh), "non-ASCII in a script served without a charset shows up as mojibake"


def test_every_floating_orb_variant_paints_in_every_state():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from interface.orb_variants import STYLES, VariantOrb
    assert len(STYLES) >= 8
    pm = QPixmap(300, 300)
    for style in STYLES:
        orb = VariantOrb(style)
        orb.timer.stop()
        for state in ("IDLE", "LISTENING", "PROCESSING", "SPEAKING", "SLEEP", "ERROR"):
            orb.set_state(state)
            orb._view_scale = 1.0
            orb.render(pm)          # an exception inside paintEvent aborts the process
    assert app is not None


def test_floating_orb_style_can_be_switched_while_running():
    import os
    import types
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QHBoxLayout, QWidget
    app = QApplication.instance() or QApplication([])
    from interface.ui import EnhancedFlexieOrb, FlexieUI
    host = QWidget()
    layout = QHBoxLayout(host)
    first = FlexieUI._make_orb("")
    first.timer.stop()
    layout.addWidget(first)
    fake = types.SimpleNamespace(layout=layout, orb=first, _make_orb=FlexieUI._make_orb, applied=[])
    fake._apply_mode_visuals = lambda m: fake.applied.append(m)
    first.mode = "hacker"
    first.set_state("LISTENING")
    assert type(first) is EnhancedFlexieOrb
    for style in ("hud", "eye", "classic", "nonsense"):
        FlexieUI._swap_orb(fake, style)
        fake.orb.timer.stop()
        assert fake.orb.mode == "hacker" and fake.orb.state == "LISTENING", style      # mode and state carry over
        assert layout.indexOf(fake.orb) >= 0 and layout.count() == 1, style            # exactly one orb in the layout
    assert type(fake.orb) is EnhancedFlexieOrb                                          # unknown style fell back safely
    assert app is not None


def test_settings_orb_styles_match_the_orbs_that_exist():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.settings_service import ORB_STYLES
    from interface.orb_variants import STYLES
    assert set(ORB_STYLES) == {"classic", "hud", *STYLES}

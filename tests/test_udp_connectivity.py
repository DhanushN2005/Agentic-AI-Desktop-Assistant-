"""Regression tests: text input / UI → orchestrator connectivity.

Root cause these tests lock down: the PyQt HUD (`interface/ui.py`) and the web
bridge (`interface/web_ui_bridge.py`) are launched as *scripts*, so Python puts
``interface/`` — not the project root — on ``sys.path``. The ``utils.udp_auth``
import therefore failed, commands were sent WITHOUT the per-run token, and the
orchestrator rejected every one of them ("UDP: rejected message without valid
token"), which looked exactly like "typing into the assistant does nothing".
"""
import pathlib
import re
import socket
import sys

import pytest

import utils.udp_auth as udp_auth
from utils.udp_auth import get_token, pack, publish_token, unpack

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    """Isolate the token file + clear the env so get_token() must use the file."""
    path = tmp_path / ".flexie_udp_token"
    monkeypatch.setattr(udp_auth, "TOKEN_FILE", str(path))
    monkeypatch.delenv(udp_auth.ENV_VAR, raising=False)
    return path


# --- shared token: the actual connectivity fix -------------------------------

def test_standalone_client_uses_published_token(token_file):
    """A process started by hand must share main.py's per-run token."""
    assert publish_token("run-token-abc") is True
    assert token_file.read_text(encoding="utf-8") == "run-token-abc"
    assert get_token() == "run-token-abc"
    # …so its datagrams are accepted, and unsigned ones still are not.
    assert unpack(pack("open youtube")) == "open youtube"
    assert unpack("open youtube") is None


def test_get_token_generates_and_persists_when_nothing_set(token_file):
    """With no env var and no file, a token is created and written to disk so
    the next hand-started process agrees instead of minting its own."""
    tok = get_token()
    assert tok
    assert token_file.read_text(encoding="utf-8") == tok
    # Second "process": same file, still no env var → identical token.
    assert get_token() == tok


def test_env_var_still_wins_over_token_file(token_file, monkeypatch):
    """main.py owns the token for its run; the file must never override it."""
    publish_token("stale-token")
    monkeypatch.setenv(udp_auth.ENV_VAR, "per-run-env-token")
    assert get_token() == "per-run-env-token"
    assert unpack(pack("wake up")) == "wake up"
    assert unpack("TOKEN:stale-token wake up") is None


def test_client_picks_up_rotated_token(token_file, monkeypatch):
    """A long-running Bridge/HUD must self-heal after Flexie restarts."""
    publish_token("token-run-1")
    assert unpack(pack("ping")) == "ping"

    # Flexie restarts → main.py publishes a fresh per-run token.
    monkeypatch.setenv(udp_auth.ENV_VAR, "token-run-2")
    publish_token("token-run-2")
    monkeypatch.delenv(udp_auth.ENV_VAR, raising=False)

    assert get_token() == "token-run-2"              # client follows the file
    assert unpack("TOKEN:token-run-1 ping") is None  # old token now dead


def test_main_publishes_token_for_child_processes():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "publish_token" in src


# --- entry points must be importable (sys.path bootstrap) --------------------

@pytest.mark.parametrize("rel", ["interface/ui.py", "interface/web_ui_bridge.py"])
def test_entry_point_bootstraps_project_root_on_sys_path(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "sys.path.insert(0, _ROOT_DIR)" in src, rel
    # The bootstrap has to run before any real project import, or it is useless.
    first_project_import = re.search(r"^\s*from utils[.\s]", src, re.MULTILINE)
    assert first_project_import, f"{rel} has no project import to guard"
    assert src.index("sys.path.insert(0, _ROOT_DIR)") < first_project_import.start()


@pytest.mark.parametrize("rel", ["interface/ui.py", "interface/web_ui_bridge.py"])
def test_senders_fail_closed(rel):
    """Never send an unsigned datagram: it is rejected, so the UI would look dead."""
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "pack as _udp_pack" in src
    # Old buggy shape: the pack failure was swallowed and the raw message sent.
    assert "_udp_pack(msg)\n        except" not in src
    assert "return False" in src


def test_bridge_relays_authenticated_datagram_end_to_end(tmp_path, monkeypatch):
    """End-to-end proof of the fix.

    The bridge module is loaded the way Python loads it when launched as
    ``python interface/web_ui_bridge.py`` (only ``interface/`` on sys.path). Its
    own bootstrap must put the project root back, and the datagram that lands on
    the orchestrator's port must carry this run's token.
    """
    src = (ROOT / "interface" / "web_ui_bridge.py").read_text(encoding="utf-8")
    src = src.split('if __name__ == "__main__":')[0]  # no servers / no browser

    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        listener.bind(("127.0.0.1", 9887))
    except OSError:
        listener.close()
        pytest.skip("UDP 9887 busy — Flexie is already running")
    listener.settimeout(5)

    monkeypatch.setattr(udp_auth, "TOKEN_FILE", str(tmp_path / ".flexie_udp_token"))
    monkeypatch.delenv(udp_auth.ENV_VAR, raising=False)
    publish_token("e2e-run-token")

    # Emulate the script launch: sys.path[0] is the interface/ directory only.
    monkeypatch.setattr(
        sys, "path",
        [str(ROOT / "interface")] + [p for p in sys.path if p not in ("", str(ROOT))],
    )

    namespace = {
        "__file__": str(ROOT / "interface" / "web_ui_bridge.py"),
        "__name__": "flexie_bridge_probe",
    }
    try:
        exec(compile(src, "web_ui_bridge.py", "exec"), namespace)  # runs the real bootstrap
        assert str(ROOT) in sys.path, "bridge did not bootstrap the project root"
        # `import utils` no longer raises: the old failure that made the UI "dead".
        assert namespace["_send_udp"]("open youtube") is True
        data, _ = listener.recvfrom(65535)
    finally:
        listener.close()

    raw = data.decode("utf-8")
    assert raw.startswith("TOKEN:")
    assert unpack(raw) == "open youtube"


# --- dashboard URL / token injection ----------------------------------------

def test_dashboard_url_matches_bridge_http_port():
    bridge = (ROOT / "interface" / "web_ui_bridge.py").read_text(encoding="utf-8")
    ui = (ROOT / "interface" / "ui.py").read_text(encoding="utf-8")
    port = re.search(r"^HTTP_PORT\s*=\s*(\d+)", bridge, re.MULTILINE).group(1)
    # ui.py must open the page the bridge actually serves (token injected there).
    assert f"localhost:{port}" in ui
    assert "localhost:7860" not in ui  # stale dead-link port


def test_web_ui_detects_uninjected_token():
    html = (ROOT / "interface" / "web_ui.html").read_text(encoding="utf-8")
    assert "TOKEN_INJECTED" in html
    assert "NO TOKEN" in html
    # sendCmd must keep the user's text when the link is down.
    assert "if (sendRaw(val))" in html


# --- orchestrator-side feedback + DEEP_SEARCH routing ------------------------

def test_auth_rejection_is_logged_and_surfaced_once():
    import logging

    from core.orchestrator import FlexieOrchestrator

    class _Stub:
        def __init__(self):
            self.logger = logging.getLogger("test.flexie")
            self.sent = []

        def send_to_ui(self, tag, value):
            self.sent.append((tag, value))

    stub = _Stub()
    FlexieOrchestrator._note_auth_rejection(stub)
    assert stub.sent and stub.sent[0][0] == "SAY"
    assert "token" in stub.sent[0][1].lower()
    # Rate-limited: a burst of rejected datagrams must not spam the UI.
    for _ in range(5):
        FlexieOrchestrator._note_auth_rejection(stub)
    assert len(stub.sent) == 1


def test_network_loop_uses_rejection_notifier():
    src = (ROOT / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assert "self._note_auth_rejection()" in src
    assert "rejected message without valid token" in src


def test_deep_search_prefix_is_routed_to_research():
    """The PyQt spotlight sends '?query' as DEEP_SEARCH:<query>."""
    src = (ROOT / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assert 'msg.startswith("DEEP_SEARCH:")' in src

    from core.router import IntentRouter
    intent, confidence = IntentRouter().route("research quantum computing")
    assert intent == "research"
    assert confidence > 0.5


def test_main_publishes_token_after_deep_search_routing():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "publish_token" in src

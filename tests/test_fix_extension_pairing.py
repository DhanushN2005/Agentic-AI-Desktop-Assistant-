"""The browser extension could never get its API token: Chrome sends no Origin header for an extension's
own pages, so the old origin-based trust check never matched. These tests pin the pairing-key design."""
import base64
import hashlib
import json
import pathlib
import queue
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_manifest_key_gives_the_fixed_extension_id():
    from interface.api_server import FLEXIE_EXTENSION_ID
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    der = base64.b64decode(manifest["key"])
    derived = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(der).hexdigest()[:32])
    assert derived == FLEXIE_EXTENSION_ID and len(FLEXIE_EXTENSION_ID) == 32


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import interface.api_server as api
    monkeypatch.setattr(api, "PAIRING_KEY_FILE", str(tmp_path / "pairing.key"))
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "t" * 32)
    monkeypatch.delenv("FLEXIE_EXTENSION_IDS", raising=False)
    orch = types.SimpleNamespace(cmd_queue=queue.Queue(), active=True, current_mode="professional")
    return TestClient(api.create_app(orch)), api


def test_pairing_key_is_created_random_and_stable(tmp_path):
    import interface.api_server as api
    path = str(tmp_path / "k")
    first = api.ensure_pairing_key(path)
    assert len(first) == 64 and api.ensure_pairing_key(path) == first
    flipped = first[:-1] + ("0" if first[-1] != "0" else "1")
    assert api.pairing_key_matches(first, path) and not api.pairing_key_matches(flipped, path)
    assert not api.pairing_key_matches("", path) and not api.pairing_key_matches("short", path)


def test_health_issues_the_token_to_the_paired_extension_only(client):
    c, api = client
    key = api.ensure_pairing_key(api.PAIRING_KEY_FILE)
    assert "token" in c.get("/health", headers={api.PAIRING_HEADER: key}).json()
    for headers in ({}, {api.PAIRING_HEADER: "x" * 64}, {api.PAIRING_HEADER: key[:-1]},
                    {"Origin": "chrome-extension://" + "a" * 32}, {"Origin": "http://evil.example"}):
        body = c.get("/health", headers=headers).json()
        assert "token" not in body and body["paired"] is False, headers
    assert "token" in c.get("/health", headers={"Origin": "http://localhost:8766"}).json()   # dashboard still works


def test_paired_extension_can_then_run_commands(client):
    c, api = client
    key = api.ensure_pairing_key(api.PAIRING_KEY_FILE)
    token = c.get("/health", headers={api.PAIRING_HEADER: key}).json()["token"]
    r = c.post("/command", json={"command": "what time is it"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert c.post("/command", json={"command": "x"}).status_code == 401


def test_web_pages_cannot_send_the_pairing_header(client):
    """A cross-origin page would need a CORS preflight to send it, and the header is not allow-listed."""
    c, api = client
    r = c.options("/health", headers={"Origin": "http://localhost:8766", "Access-Control-Request-Method": "GET",
                                      "Access-Control-Request-Headers": api.PAIRING_HEADER})
    assert api.PAIRING_HEADER.lower() not in (r.headers.get("access-control-allow-headers") or "").lower()


def test_extension_pages_send_the_key_and_popup_has_no_inline_script():
    for name in ("background.js", "sidebar.js", "popup.js"):
        src = (EXT / name).read_text(encoding="utf-8")
        assert "X-Flexie-Pairing" in src and 'getURL("pairing.key")' in src, name
    popup = (EXT / "popup.html").read_text(encoding="utf-8")
    assert '<script src="popup.js"></script>' in popup
    assert "<script>" not in popup                      # MV3 blocks inline scripts in extension pages
    assert "NOT PAIRED" in (EXT / "popup.js").read_text(encoding="utf-8")
    assert "extension/pairing.key" in (ROOT / ".gitignore").read_text(encoding="utf-8")

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from interface.api_server import create_app


@pytest.fixture
def test_client(monkeypatch):
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "valid-test-token")
    mock_orch = MagicMock()
    mock_orch.active = True
    mock_orch.current_mode = "general"
    mock_orch.cmd_queue = MagicMock()

    app = create_app(mock_orch)
    client = TestClient(app)
    return client, mock_orch


def test_health_endpoint(test_client):
    client, mock_orch = test_client
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    # No Origin header (curl / untrusted caller) must NOT receive the token.
    assert "token" not in resp.json()


def test_health_token_only_for_trusted_origin(test_client, monkeypatch):
    client, _ = test_client
    ok = client.get("/health", headers={"Origin": "http://localhost:8766"})
    assert ok.json()["token"] == "valid-test-token"
    evil = client.get("/health", headers={"Origin": "chrome-extension://evilextension"})
    assert "token" not in evil.json()
    other = client.get("/health", headers={"Origin": "http://localhost:9999"})
    assert "token" not in other.json()


def test_health_token_for_configured_extension(monkeypatch):
    monkeypatch.setenv("FLEXIE_EXTENSION_IDS", "abcdef")
    from interface.api_server import _allowed_origins
    assert "chrome-extension://abcdef" in _allowed_origins()


def test_command_requires_auth(test_client):
    client, _ = test_client
    resp = client.post("/api/flexie/commands", json={"command": "open chrome"})
    assert resp.status_code == 401


def test_command_with_auth_token(test_client):
    client, mock_orch = test_client
    headers = {"Authorization": "Bearer valid-test-token"}
    resp = client.post("/api/flexie/commands", json={"command": "open chrome"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    mock_orch.cmd_queue.put.assert_called_with("open chrome")


def test_openai_compatible_chat_completion(test_client):
    client, mock_orch = test_client
    mock_orch.brain.ask.return_value = "hello from flexie"
    headers = {"Authorization": "Bearer valid-test-token"}
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "flexie", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "hello from flexie"


def test_approve_and_reject_endpoints(test_client):
    client, mock_orch = test_client
    headers = {"Authorization": "Bearer valid-test-token"}

    mock_orch.permission_system = MagicMock()
    mock_orch.permission_system.approve_request.return_value = True
    mock_orch.permission_system.reject_request.return_value = True

    resp_approve = client.post("/api/flexie/approve", json={"request_id": "req-123"}, headers=headers)
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "approved"

    resp_reject = client.post("/api/flexie/reject", json={"request_id": "req-123"}, headers=headers)
    assert resp_reject.status_code == 200
    assert resp_reject.json()["status"] == "rejected"

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from interface.api_server import create_app


def test_page_assistant_endpoint(monkeypatch):
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "test-token")
    mock_orch = MagicMock()
    mock_orch.brain = MagicMock()
    mock_orch.brain.ask.return_value = "This page discusses autonomous AI agents."

    app = create_app(mock_orch)
    client = TestClient(app)

    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "query": "Summarize this article",
        "url": "https://example.com/article",
        "title": "Autonomous Agents in 2026",
        "page_content": "Full article text discussing agent loops and tools...",
        "selected_text": "agent loops and tools",
        "action": "summarize"
    }

    resp = client.post("/api/flexie/page-assistant", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "autonomous AI agents" in data["answer"]
    assert mock_orch.brain.ask.called

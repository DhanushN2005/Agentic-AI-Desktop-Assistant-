"""Unit and integration tests for Phase 5: Model Hub & Local OpenAI Bridge."""
import json
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch
import pytest

from core.model_hub import (
    CircuitBreaker,
    ModelHub,
    OpenAIBridgeServer,
    TaskType,
    TokenTracker,
)


class TestTaskRoutingAndConfig:
    def test_default_task_mappings(self):
        hub = ModelHub()
        plan_mapping = hub.get_mapping_for_task(TaskType.PLAN)
        assert "deepseek" in plan_mapping.local_model or "deepseek" in plan_mapping.cloud_model

        code_mapping = hub.get_mapping_for_task(TaskType.CODE)
        assert "coder" in code_mapping.local_model or "coder" in code_mapping.cloud_model

        route_mapping = hub.get_mapping_for_task(TaskType.ROUTE)
        assert route_mapping.max_tokens <= 1024


class TestCircuitBreaker:
    def test_circuit_trips_after_failures(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=2.0)
        assert cb.is_available("groq") is True

        cb.record_failure("groq")
        assert cb.is_available("groq") is True
        cb.record_failure("groq")
        assert cb.is_available("groq") is True

        # 3rd failure trips the breaker
        cb.record_failure("groq")
        assert cb.is_available("groq") is False

        # Wait for cooldown
        time.sleep(2.1)
        assert cb.is_available("groq") is True

    def test_record_success_resets_breaker(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("openai")
        assert cb._failures.get("openai") == 1
        cb.record_success("openai")
        assert cb._failures.get("openai") == 0


class TestTokenTracker:
    def test_token_tracking_and_reporting(self):
        tracker = TokenTracker()
        tracker.record("groq", "code", prompt_tokens=100, completion_tokens=50, job_id="job_42")
        tracker.record("groq", "code", prompt_tokens=200, completion_tokens=100, job_id="job_42")

        job_rep = tracker.get_job_report("job_42")
        assert job_rep["total_tokens"] == 450
        assert job_rep["calls"] == 2

        summary = tracker.get_summary_report()
        assert summary["total_tokens"] == 450
        assert summary["estimated_cost_usd"] > 0


class TestCheapFirstAndFailover:
    def test_cheap_first_uses_ollama_when_available(self):
        hub = ModelHub()
        with patch.object(hub, "check_ollama_health", return_value=(True, ["llama3.2:1b"])):
            with patch.object(hub, "_execute_ollama", return_value="Local answer"):
                mock_brain = MagicMock()
                res = hub.route_and_ask("hi", task=TaskType.GENERAL, brain=mock_brain)
                assert res == "Local answer"
                mock_brain.ask.assert_not_called()

    def test_failover_to_cloud_when_ollama_fails(self):
        hub = ModelHub()
        with patch.object(hub, "check_ollama_health", return_value=(False, [])):
            mock_brain = MagicMock()
            mock_brain.ask.return_value = "Cloud answer"
            res = hub.route_and_ask("hi", task=TaskType.GENERAL, brain=mock_brain)
            assert res == "Cloud answer"
            mock_brain.ask.assert_called_once()

    def test_exponential_backoff_on_429(self):
        hub = ModelHub()
        with patch.object(hub, "check_ollama_health", return_value=(False, [])):
            mock_brain = MagicMock()
            # Raises 429 once, then succeeds
            mock_brain.ask.side_effect = [
                Exception("Rate limit 429 Too Many Requests"),
                "Success after backoff",
            ]
            res = hub.route_and_ask("test backoff", task=TaskType.CODE, brain=mock_brain)
            assert res == "Success after backoff"
            assert mock_brain.ask.call_count == 2


class TestOpenAIBridgeServer:
    def test_bridge_endpoints(self):
        hub = ModelHub()
        bridge = OpenAIBridgeServer(hub, port=9898, token="test-secret-token")
        assert bridge.start() is True

        time.sleep(0.5)
        base_url = "http://127.0.0.1:9898"

        try:
            # 1. Unauthorized request
            req_unauth = urllib.request.Request(f"{base_url}/v1/models")
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req_unauth, timeout=3.0)
            assert exc.value.code == 401

            # 2. Authorized GET /v1/models
            req_models = urllib.request.Request(
                f"{base_url}/v1/models",
                headers={"Authorization": "Bearer test-secret-token"},
            )
            with urllib.request.urlopen(req_models, timeout=3.0) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert data["object"] == "list"
                assert len(data["data"]) >= 1

            # 3. Authorized POST /v1/chat/completions
            with patch.object(hub, "route_and_ask", return_value="print('hello')"):
                payload = json.dumps({
                    "model": "qwen-2.5-coder-32b",
                    "messages": [{"role": "user", "content": "write python"}],
                }).encode("utf-8")
                req_chat = urllib.request.Request(
                    f"{base_url}/v1/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": "Bearer test-secret-token",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req_chat, timeout=3.0) as resp:
                    assert resp.status == 200
                    chat_data = json.loads(resp.read().decode("utf-8"))
                    assert chat_data["object"] == "chat.completion"
                    assert chat_data["choices"][0]["message"]["content"] == "print('hello')"

        finally:
            bridge.stop()

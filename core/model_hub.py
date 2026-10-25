"""Model Hub: task-based routing, cheap-first cascade, resilience, and OpenAI bridge.

Features:
- Task-based model routing (route/classify -> fast, plan -> reasoning, code/patch -> coding, summary -> cheap).
- Configurable models via context/model_config.json or Config defaults.
- Cheap-first: attempts local Ollama first, escalating to cloud providers only on failure.
- Circuit breaker: skips providers for 5 minutes after repeated failures.
- Exponential backoff with jitter on 429 and 5xx errors.
- Token and quota tracker with per-job cost and token reporting.
- Optional OpenAI-compatible local bridge server (localhost only, bearer token auth).
"""
from __future__ import annotations

import http.server
import json
import logging
import os
import random
import re
import socketserver
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.config import Config

logger = logging.getLogger("flexie.model_hub")


class TaskType(str, Enum):
    ROUTE = "route"
    CLASSIFY = "classify"
    PLAN = "plan"
    CODE = "code"
    PATCH = "patch"
    SUMMARY = "summary"
    GENERAL = "general"


@dataclass
class ModelTaskMapping:
    local_model: str
    cloud_provider: str
    cloud_model: str
    max_tokens: int
    temperature: float


DEFAULT_TASK_MAPPINGS: Dict[str, ModelTaskMapping] = {
    TaskType.ROUTE.value: ModelTaskMapping("llama3.2:1b", "groq", "llama-3.1-8b-instant", 512, 0.1),
    TaskType.CLASSIFY.value: ModelTaskMapping("llama3.2:1b", "groq", "llama-3.1-8b-instant", 512, 0.1),
    TaskType.PLAN.value: ModelTaskMapping("deepseek-r1:latest", "groq", "deepseek-r1-distill-llama-70b", 4096, 0.3),
    TaskType.CODE.value: ModelTaskMapping("qwen2.5-coder:7b", "groq", "qwen-2.5-coder-32b", 4096, 0.2),
    TaskType.PATCH.value: ModelTaskMapping("qwen2.5-coder:7b", "groq", "qwen-2.5-coder-32b", 4096, 0.2),
    TaskType.SUMMARY.value: ModelTaskMapping("llama3.2:3b", "groq", "llama-3.1-8b-instant", 1024, 0.5),
    TaskType.GENERAL.value: ModelTaskMapping("llama3.2:3b", "groq", "llama-3.1-8b-instant", 2048, 0.7),
}


class CircuitBreaker:
    """Tracks provider failures and enforces cooldown periods."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 300.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: Dict[str, int] = {}
        self._tripped_at: Dict[str, float] = {}
        self._lock = threading.Lock()

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._failures[provider] = 0
            self._tripped_at.pop(provider, None)

    def record_failure(self, provider: str, is_server_or_rate_limit: bool = True) -> None:
        with self._lock:
            count = self._failures.get(provider, 0) + 1
            self._failures[provider] = count
            if count >= self.failure_threshold:
                self._tripped_at[provider] = time.time()
                logger.warning("Circuit breaker tripped for provider '%s' (cooling down for %0.1fs)", provider, self.cooldown_seconds)

    def is_available(self, provider: str) -> bool:
        with self._lock:
            tripped_time = self._tripped_at.get(provider)
            if tripped_time is None:
                return True
            elapsed = time.time() - tripped_time
            if elapsed >= self.cooldown_seconds:
                # Half-open trial
                logger.info("Circuit breaker cooldown passed for '%s'. Entering half-open trial.", provider)
                return True
            return False


@dataclass
class TokenRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class TokenTracker:
    """Thread-safe tracking of tokens and estimated costs across jobs and providers."""

    # Approximate price per 1k tokens in USD for cloud models
    PRICE_PER_1K = {
        "groq": 0.0001,
        "openai": 0.0015,
        "gemini": 0.0005,
        "anthropic": 0.003,
        "ollama": 0.0,
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._job_tokens: Dict[str, TokenRecord] = {}
        self._provider_tokens: Dict[str, TokenRecord] = {}
        self._task_tokens: Dict[str, TokenRecord] = {}

    def record(self, provider: str, task: str, prompt_tokens: int, completion_tokens: int, job_id: Optional[str] = None) -> None:
        with self._lock:
            # By provider
            p_rec = self._provider_tokens.setdefault(provider, TokenRecord())
            p_rec.prompt_tokens += prompt_tokens
            p_rec.completion_tokens += completion_tokens
            p_rec.calls += 1

            # By task
            t_rec = self._task_tokens.setdefault(task, TokenRecord())
            t_rec.prompt_tokens += prompt_tokens
            t_rec.completion_tokens += completion_tokens
            t_rec.calls += 1

            # By job
            if job_id:
                j_rec = self._job_tokens.setdefault(job_id, TokenRecord())
                j_rec.prompt_tokens += prompt_tokens
                j_rec.completion_tokens += completion_tokens
                j_rec.calls += 1

    def get_job_report(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            rec = self._job_tokens.get(job_id, TokenRecord())
            return {
                "job_id": job_id,
                "prompt_tokens": rec.prompt_tokens,
                "completion_tokens": rec.completion_tokens,
                "total_tokens": rec.total_tokens,
                "calls": rec.calls,
            }

    def get_summary_report(self) -> Dict[str, Any]:
        with self._lock:
            total_prompt = sum(r.prompt_tokens for r in self._provider_tokens.values())
            total_comp = sum(r.completion_tokens for r in self._provider_tokens.values())
            est_cost = sum(
                (r.total_tokens / 1000.0) * self.PRICE_PER_1K.get(p, 0.0005)
                for p, r in self._provider_tokens.items()
            )
            return {
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_comp,
                "total_tokens": total_prompt + total_comp,
                "estimated_cost_usd": round(est_cost, 6),
                "providers": {p: asdict(r) for p, r in self._provider_tokens.items()},
                "tasks": {t: asdict(r) for t, r in self._task_tokens.items()},
            }


class ModelHub:
    """Unified AI Model Hub managing task-based routing, cheap-first cascade, and resilience."""

    _instance: Optional[ModelHub] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ModelHub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, config_file: Optional[str] = None):
        self.circuit_breaker = CircuitBreaker()
        self.tracker = TokenTracker()
        self.config_file = config_file or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "context", "model_config.json"
        )
        self.task_mappings = self._load_task_mappings()
        self._bridge_server: Optional[OpenAIBridgeServer] = None

    def _load_task_mappings(self) -> Dict[str, ModelTaskMapping]:
        """Load mappings from JSON configuration with built-in defaults."""
        mappings = dict(DEFAULT_TASK_MAPPINGS)
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for task_name, m_data in data.items():
                    mappings[task_name] = ModelTaskMapping(
                        local_model=m_data.get("local_model", "llama3.2:1b"),
                        cloud_provider=m_data.get("cloud_provider", "groq"),
                        cloud_model=m_data.get("cloud_model", "llama-3.1-8b-instant"),
                        max_tokens=m_data.get("max_tokens", 2048),
                        temperature=m_data.get("temperature", 0.3),
                    )
            except Exception as e:
                logger.warning("Could not read %s, using defaults: %s", self.config_file, e)
        return mappings

    def get_mapping_for_task(self, task: TaskType | str) -> ModelTaskMapping:
        t_key = task.value if isinstance(task, TaskType) else str(task)
        return self.task_mappings.get(t_key, DEFAULT_TASK_MAPPINGS[TaskType.GENERAL.value])

    def check_ollama_health(self) -> Tuple[bool, List[str]]:
        """Verify reachability and pulled models of local Ollama server."""
        ollama_url = getattr(Config, "OLLAMA_URL", "http://localhost:11434").rstrip("/")
        try:
            req = urllib.request.Request(f"{ollama_url}/api/tags", headers={"User-Agent": "FlexieModelHub/2.0"})
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m.get("name", "") for m in data.get("models", [])]
                    self.circuit_breaker.record_success("ollama")
                    return True, models
        except Exception:
            self.circuit_breaker.record_failure("ollama")
        return False, []

    def _execute_ollama(self, prompt: str, model_name: str, system: Optional[str] = None, timeout: float = 12.0) -> Optional[str]:
        """Direct query to local Ollama server with exponential backoff on retry."""
        ollama_url = getattr(Config, "OLLAMA_URL", "http://localhost:11434").rstrip("/")
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    f"{ollama_url}/api/generate",
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        text = res_json.get("response", "").strip()
                        if text:
                            self.circuit_breaker.record_success("ollama")
                            return text
            except Exception as e:
                logger.debug("Ollama query attempt %d failed: %s", attempt + 1, e)
                time.sleep(0.3 + random.uniform(0, 0.2))

        self.circuit_breaker.record_failure("ollama")
        return None

    def route_and_ask(
        self,
        prompt: str,
        task: TaskType | str = TaskType.GENERAL,
        brain: Any = None,
        system_override: Optional[str] = None,
        job_id: Optional[str] = None,
        use_rag: bool = False,
    ) -> str:
        """Execute a task-based query using cheap-first local trial and resilient cloud failover."""
        t_key = task.value if isinstance(task, TaskType) else str(task)
        mapping = self.get_mapping_for_task(t_key)

        # 1. Cheap-First: try local Ollama if enabled and circuit is available
        cheap_first = getattr(Config, "CHEAP_FIRST_ENABLED", True)
        if cheap_first and self.circuit_breaker.is_available("ollama"):
            healthy, models = self.check_ollama_health()
            if healthy and models:
                chosen_local = mapping.local_model if mapping.local_model in models else models[0]
                local_res = self._execute_ollama(prompt, chosen_local, system=system_override)
                if local_res:
                    est_in = len(prompt) // 4
                    est_out = len(local_res) // 4
                    self.tracker.record("ollama", t_key, est_in, est_out, job_id=job_id)
                    return local_res

        # 2. Cloud Failover via Brain or ProviderManager
        if brain and hasattr(brain, "ask"):
            # Execute with exponential backoff on 429/5xx errors
            for attempt in range(3):
                try:
                    res = brain.ask(
                        prompt,
                        system_override=system_override,
                        use_rag=use_rag,
                        max_tokens=mapping.max_tokens,
                    )
                    if res:
                        est_in = len(prompt) // 4
                        est_out = len(res) // 4
                        self.tracker.record(mapping.cloud_provider, t_key, est_in, est_out, job_id=job_id)
                        self.circuit_breaker.record_success(mapping.cloud_provider)
                        return res
                except Exception as e:
                    err_str = str(e)
                    is_rate_or_server = "429" in err_str or "500" in err_str or "503" in err_str
                    self.circuit_breaker.record_failure(mapping.cloud_provider, is_rate_or_server)
                    if is_rate_or_server and attempt < 2:
                        delay = min(4.0, (1.0 * (2 ** attempt))) + random.uniform(0.1, 0.4)
                        logger.warning("Cloud LLM rate/server error (%s). Backing off for %.2fs...", err_str, delay)
                        time.sleep(delay)
                    else:
                        break

        return ""

    def start_openai_bridge(self, port: Optional[int] = None, token: Optional[str] = None) -> bool:
        """Start the localhost-only OpenAI-compatible API bridge."""
        if self._bridge_server is not None:
            return True
        b_port = port or getattr(Config, "OPENAI_BRIDGE_PORT", 9899)
        from utils.udp_auth import get_current_token
        auth_token = token or get_current_token()
        self._bridge_server = OpenAIBridgeServer(self, port=b_port, token=auth_token)
        return self._bridge_server.start()

    def stop_openai_bridge(self) -> None:
        """Stop the local OpenAI bridge server."""
        if self._bridge_server:
            self._bridge_server.stop()
            self._bridge_server = None


class _OpenAIBridgeHandler(http.server.BaseHTTPRequestHandler):
    """Handles OpenAI-compatible HTTP requests securely on localhost."""

    hub: ModelHub = None  # Bound dynamically
    auth_token: str = ""

    def _check_auth(self) -> bool:
        auth_hdr = self.headers.get("Authorization", "")
        if not auth_hdr.startswith("Bearer "):
            return False
        provided = auth_hdr.split("Bearer ", 1)[1].strip()
        return bool(self.auth_token and provided == self.auth_token)

    def do_GET(self):
        if self.path == "/v1/models":
            if not self._check_auth():
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
                return

            models_data = {
                "object": "list",
                "data": [
                    {"id": "gpt-4o-mini", "object": "model", "owned_by": "flexie"},
                    {"id": "qwen-2.5-coder-32b", "object": "model", "owned_by": "flexie"},
                    {"id": "deepseek-r1", "object": "model", "owned_by": "flexie"},
                ],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(models_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            if not self._check_auth():
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
                return

            content_len = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_len).decode("utf-8")
            try:
                body = json.loads(raw_body)
                messages = body.get("messages", [])
                prompt = messages[-1].get("content", "") if messages else ""
                system_prompt = messages[0].get("content", "") if len(messages) > 1 and messages[0].get("role") == "system" else None

                # Route via ModelHub
                ans = self.hub.route_and_ask(prompt, task=TaskType.CODE, system_override=system_prompt)
                resp_payload = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body.get("model", "qwen-2.5-coder-32b"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": ans},
                            "finish_reason": "stop",
                        }
                    ],
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp_payload).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class OpenAIBridgeServer:
    """Localhost-only HTTP server exposing OpenAI-compatible endpoints."""

    def __init__(self, hub: ModelHub, port: int = 9899, token: str = "flexie-local"):
        self.hub = hub
        self.port = port
        self.token = token
        self._server: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        handler = _OpenAIBridgeHandler
        handler.hub = self.hub
        handler.auth_token = self.token

        try:
            # Bind ONLY to localhost for safety
            self._server = socketserver.TCPServer(("127.0.0.1", self.port), handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info("OpenAI API Bridge listening on http://127.0.0.1:%d", self.port)
            return True
        except Exception as e:
            logger.error("Failed to start OpenAI Bridge Server on port %d: %s", self.port, e)
            return False

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

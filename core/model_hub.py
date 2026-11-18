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

import hmac
import http.server
import json
import logging
import os
import random
import socketserver
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from core.inference.ollama import choose_chat_model, ollama_available, ollama_base_url, set_ollama_health
from core.telemetry.pricing import BLENDED_PER_1K
from core.telemetry.usage import begin_job, end_job, get_tracker, track_llm
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


DEFAULT_TASK_MAPPINGS: dict[str, ModelTaskMapping] = {
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
        self._failures: dict[str, int] = {}
        self._tripped_at: dict[str, float] = {}
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
                # Half-open trial: one more failure re-trips immediately (count stays >= threshold)
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
    """Per-job / per-provider token report.

    The single ledger of LLM calls is ``core.telemetry.usage`` (``track_llm``). This class no longer
    records estimates for calls the ledger already sees: reports merge the ledger's per-job totals
    with whatever was recorded explicitly through ``record()`` (non-LLM or externally measured usage).
    """

    # Approximate price per 1k tokens in USD for cloud models
    PRICE_PER_1K = BLENDED_PER_1K  # single source of truth: core/telemetry/pricing.py

    def __init__(self):
        self._lock = threading.Lock()
        self._job_tokens: dict[str, TokenRecord] = {}
        self._provider_tokens: dict[str, TokenRecord] = {}
        self._task_tokens: dict[str, TokenRecord] = {}

    def record(self, provider: str, task: str, prompt_tokens: int, completion_tokens: int, job_id: str | None = None) -> None:
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

    def get_job_report(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._job_tokens.get(job_id, TokenRecord())
            prompt, completion, calls = rec.prompt_tokens, rec.completion_tokens, rec.calls
        try:
            led = get_tracker().job_totals(job_id)
            prompt += led["prompt_tokens"]
            completion += led["completion_tokens"]
            calls += led["calls"]
        except Exception:  # noqa: S110
            pass
        return {
            "job_id": job_id,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "calls": calls,
        }

    def get_summary_report(self) -> dict[str, Any]:
        with self._lock:
            total_prompt = sum(r.prompt_tokens for r in self._provider_tokens.values())
            total_comp = sum(r.completion_tokens for r in self._provider_tokens.values())
            est_cost = sum(
                (r.total_tokens / 1000.0) * self.PRICE_PER_1K.get(p, 0.0005)
                for p, r in self._provider_tokens.items()
            )
            providers = {p: asdict(r) for p, r in self._provider_tokens.items()}
            tasks = {t: asdict(r) for t, r in self._task_tokens.items()}
        try:  # merge the ledger (successful calls only; failures carry no tokens or cost)
            led = get_tracker().summary()
            total_prompt += led["prompt_tokens"]
            total_comp += led["completion_tokens"]
            est_cost += led["cost_usd"]
            for p, v in led["per_provider"].items():
                if v["calls"]:
                    providers.setdefault(p, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
                    providers[p]["calls"] += v["calls"]
        except Exception:  # noqa: S110
            pass
        return {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_comp,
            "total_tokens": total_prompt + total_comp,
            "estimated_cost_usd": round(est_cost, 6),
            "providers": providers,
            "tasks": tasks,
        }


class ModelHub:
    """Unified AI Model Hub managing task-based routing, cheap-first cascade, and resilience."""

    _instance: ModelHub | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ModelHub:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self, config_file: str | None = None):
        self.circuit_breaker = CircuitBreaker()
        self.tracker = TokenTracker()
        self.config_file = config_file or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "context", "model_config.json"
        )
        self.task_mappings = self._load_task_mappings()
        self._bridge_server: OpenAIBridgeServer | None = None
        self._health_lock = threading.Lock()
        self._health: tuple[float, bool, list[str]] | None = None  # (checked_at, healthy, models)

    def _load_task_mappings(self) -> dict[str, ModelTaskMapping]:
        """Load mappings from JSON configuration with built-in defaults."""
        mappings = dict(DEFAULT_TASK_MAPPINGS)
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, encoding="utf-8") as f:
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

    HEALTH_TTL_SECONDS = 30.0

    def check_ollama_health(self) -> tuple[bool, list[str]]:
        """Reachability + pulled models of the local Ollama server.

        Cached for 30 s (one probe, not one per call) and shared with the rest of the app through
        ``core.inference.ollama``'s health cache. The URL comes from the shared base-url helper:
        ``Config.OLLAMA_URL`` already ends in ``/api/generate``.
        """
        now = time.time()
        with self._health_lock:
            cached = self._health
            if cached and now - cached[0] < self.HEALTH_TTL_SECONDS:
                return cached[1], list(cached[2])
        base = ollama_base_url()
        healthy, models = False, []
        if ollama_available(base):  # shared cache: skip the probe entirely when it is known down
            try:
                req = urllib.request.Request(f"{base}/api/tags", headers={"User-Agent": "FlexieModelHub/2.0"})
                with urllib.request.urlopen(req, timeout=1.2) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                        healthy = True
            except Exception as e:
                logger.debug("Ollama tags probe failed: %s", e)
                set_ollama_health(base, False)
        if healthy:
            self.circuit_breaker.record_success("ollama")
        else:
            self.circuit_breaker.record_failure("ollama")
        with self._health_lock:
            self._health = (now, healthy, models)
        return healthy, list(models)

    def _execute_ollama(self, prompt: str, model_name: str, system: str | None = None, timeout: float = 12.0,
                        max_tokens: int | None = None, temperature: float | None = None) -> str | None:
        """Single query to the local Ollama server (no retry: a failure already cost the timeout)."""
        payload: dict[str, Any] = {"model": model_name, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        options: dict[str, Any] = {}
        if max_tokens:
            options["num_predict"] = int(max_tokens)
        if temperature is not None:
            options["temperature"] = float(temperature)
        if options:
            payload["options"] = options
        try:
            req = urllib.request.Request(
                f"{ollama_base_url()}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with track_llm("ollama", model_name, prompt_text=(system or "") + "\n" + prompt) as call:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res_json = json.loads(resp.read().decode("utf-8")) if resp.status == 200 else {}
                text = (res_json.get("response") or "").strip()
                if not text:
                    call.fail("EmptyResponse")
                else:
                    call.done(text, res_json)  # exact eval counts when Ollama reports them
            if text:
                self.circuit_breaker.record_success("ollama")
                return text
        except Exception as e:
            logger.debug("Ollama query failed: %s", e)
        self.circuit_breaker.record_failure("ollama")
        return None

    def route_and_ask(
        self,
        prompt: str,
        task: TaskType | str = TaskType.GENERAL,
        brain: Any = None,
        system_override: str | None = None,
        job_id: str | None = None,
        use_rag: bool = False,
        history: list | None = None,
    ) -> str:
        """Execute a task-based query using cheap-first local trial and a single cloud failover pass.

        Token accounting is done by ``track_llm`` (the single ledger); ``job_id`` scopes it per job.
        """
        t_key = task.value if isinstance(task, TaskType) else str(task)
        mapping = self.get_mapping_for_task(t_key)
        job_token = begin_job(job_id) if job_id else None
        try:
            # 1. Cheap-First: try local Ollama if enabled and circuit is available
            cheap_first = getattr(Config, "CHEAP_FIRST_ENABLED", True)
            if cheap_first and self.circuit_breaker.is_available("ollama"):
                healthy, models = self.check_ollama_health()
                if healthy and models:
                    chosen_local = choose_chat_model(models, mapping.local_model)  # never an embedding model
                    if chosen_local:
                        local_prompt = prompt
                        hist = [m for m in (history or []) if isinstance(m, dict) and m.get("content")]
                        if hist:
                            turns = "\n".join(f"{str(m.get('role', 'user')).capitalize()}: {m['content']}" for m in hist)
                            local_prompt = f"{turns}\nUser: {prompt}"
                        local_res = self._execute_ollama(
                            local_prompt, chosen_local, system=system_override,
                            max_tokens=mapping.max_tokens, temperature=mapping.temperature)
                        if local_res:
                            return local_res

            # 2. Cloud failover via Brain (which already walks every provider once):
            #    at most one very short retry, never a retry multiplier on top of Brain's own fallback.
            if brain and hasattr(brain, "ask"):
                for attempt in range(2):
                    try:
                        kwargs = dict(system_override=system_override, use_rag=use_rag, max_tokens=mapping.max_tokens)
                        if history:
                            kwargs["history"] = history
                        res = brain.ask(prompt, **kwargs)
                        if res:
                            self.circuit_breaker.record_success(mapping.cloud_provider)
                            return res
                        break
                    except Exception as e:
                        err_str = str(e)
                        is_rate_or_server = "429" in err_str or "500" in err_str or "503" in err_str
                        self.circuit_breaker.record_failure(mapping.cloud_provider, is_rate_or_server)
                        if is_rate_or_server and attempt == 0:
                            delay = 0.25 + random.uniform(0.0, 0.15)
                            logger.warning("Cloud LLM rate/server error. One short retry in %.2fs...", delay)
                            time.sleep(delay)
                        else:
                            break

            return ""
        finally:
            if job_token is not None:
                end_job(job_token)

    def start_openai_bridge(self, port: int | None = None, token: str | None = None) -> bool:
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
        # constant-time comparison: do not leak the token through timing
        return bool(self.auth_token) and hmac.compare_digest(provided.encode("utf-8"), str(self.auth_token).encode("utf-8"))

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

            try:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len < 0 or content_len > 4_000_000:
                    raise ValueError("bad Content-Length")
                body = json.loads(self.rfile.read(content_len).decode("utf-8"))
                messages = [m for m in (body.get("messages") or []) if isinstance(m, dict)]
                prompt = messages[-1].get("content", "") if messages else ""
                system_prompt = messages[0].get("content", "") if len(messages) > 1 and messages[0].get("role") == "system" else None
                history = [
                    {"role": m.get("role", "user"), "content": m.get("content", "")}
                    for m in messages[(1 if system_prompt is not None else 0):-1]
                    if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
                ]

                # Route via ModelHub (history is honoured)
                ans = self.hub.route_and_ask(prompt, task=TaskType.CODE, system_override=system_prompt, history=history)
                created = int(time.time())
                model = body.get("model", "qwen-2.5-coder-32b")
                if body.get("stream"):
                    # Minimal SSE: the full answer as one delta, then [DONE]
                    chunk = {"id": f"chatcmpl-{created}", "object": "chat.completion.chunk", "created": created,
                             "model": model, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ans},
                                                          "finish_reason": "stop"}]}
                    payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
                    ctype = "text/event-stream"
                else:
                    payload = json.dumps({
                        "id": f"chatcmpl-{created}",
                        "object": "chat.completion",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": ans},
                                     "finish_reason": "stop"}],
                    }).encode("utf-8")
                    ctype = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                logger.warning("OpenAI bridge request failed: %s", e)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"error": "internal error"}')
        else:
            self.send_response(404)
            self.end_headers()


class OpenAIBridgeServer:
    """Localhost-only HTTP server exposing OpenAI-compatible endpoints."""

    def __init__(self, hub: ModelHub, port: int = 9899, token: str = "flexie-local"):
        self.hub = hub
        self.port = port
        self.token = token
        self._server: socketserver.BaseServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        handler = _OpenAIBridgeHandler
        handler.hub = self.hub
        handler.auth_token = self.token

        try:
            # Bind ONLY to localhost for safety
            # threaded: one slow completion must not block every other client (or /v1/models)
            socketserver.ThreadingTCPServer.daemon_threads = True
            socketserver.ThreadingTCPServer.allow_reuse_address = True
            self._server = socketserver.ThreadingTCPServer(("127.0.0.1", self.port), handler)
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

"""Local Ollama engine using the native /api/chat endpoint."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any
from urllib.parse import urlparse

from core.inference.base import EngineResponse, InferenceEngine
from core.telemetry.usage import extract_usage, get_tracker
from utils.config import Config

_HEALTH: dict[str, tuple[float, bool]] = {}
_HEALTH_TTL = 30.0


def ollama_base_url() -> str:
    raw = getattr(Config, "OLLAMA_URL", "http://localhost:11434/api/generate") or ""
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost:11434"


def ollama_available(base_url: str | None = None, opener=None, timeout: float = 1.2) -> bool:
    """Is a local Ollama server reachable? ONE process-wide cache (30 s TTL) per base URL.

    ``opener`` defaults to ``urllib.request.urlopen`` resolved at call time (so tests can patch it).
    """
    base = (base_url or ollama_base_url()).rstrip("/")
    now = time.time()
    cached = _HEALTH.get(base)
    if cached and now - cached[0] < _HEALTH_TTL:
        return cached[1]
    try:
        request = urllib.request.Request(f"{base}/api/tags")
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            reachable = response.status == 200
    except Exception:
        reachable = False
    _HEALTH[base] = (now, reachable)
    return reachable


def set_ollama_health(base_url: str | None, reachable: bool) -> None:
    """Let a caller that already probed the server (e.g. read /api/tags) refresh the shared cache."""
    _HEALTH[(base_url or ollama_base_url()).rstrip("/")] = (time.time(), bool(reachable))


def reset_health_cache() -> None:
    _HEALTH.clear()


_EMBED_HINTS = ("embed", "bge-", "minilm", "e5-", "gte-", "rerank")


def is_embedding_model(name: str) -> bool:
    lowered = (name or "").lower()
    return any(h in lowered for h in _EMBED_HINTS)


def choose_chat_model(models: list[str], preferred: str | None = None) -> str | None:
    """``preferred`` if pulled, else the first non-embedding model, else None."""
    if preferred and preferred in models:
        return preferred
    for name in models:
        if name and not is_embedding_model(name):
            return name
    return None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OllamaEngine(InferenceEngine):
    engine_id = "ollama"

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        return ollama_available(self.base_url)

    def list_models(self) -> list[str]:
        try:
            request = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(request, timeout=2.0) as response:
                data = json.loads(response.read().decode("utf-8"))
            return [item.get("name", "") for item in data.get("models", []) if item.get("name")]
        except Exception:
            return []

    def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> EngineResponse:
        if not self.available():
            raise RuntimeError("Ollama is not available")
        chosen_model = model or getattr(Config, "OLLAMA_MODEL", "llama3.2:3b")
        payload = {
            "model": chosen_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        started = time.perf_counter()
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            try:
                get_tracker().record_failure(self.engine_id, chosen_model, time.perf_counter() - started,
                                             type(exc).__name__)
            except Exception:  # telemetry must never break inference
                pass
            raise
        text = (data.get("message") or {}).get("content", "") or ""
        prompt_text = "\n".join(str(message.get("content", "")) for message in messages)
        # Ollama reports exact counts; fall back to an estimate only if they are missing.
        exact = extract_usage(data)
        prompt_tokens, completion_tokens = exact if exact else (_estimate_tokens(prompt_text), _estimate_tokens(text))
        latency = time.perf_counter() - started
        try:
            get_tracker().record(self.engine_id, chosen_model, prompt_tokens, completion_tokens,
                                 latency, estimated=exact is None)
        except Exception:  # telemetry must never break inference
            pass
        return EngineResponse(
            text=text.strip(),
            model=chosen_model,
            engine=self.engine_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_seconds=latency,
        )

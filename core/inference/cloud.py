"""Adapter that exposes an existing callable as an InferenceEngine."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from core.inference.base import EngineResponse, InferenceEngine


class CallableEngine(InferenceEngine):
    """Wrap ``brain.ask`` (or any prompt -> text function) without a circular import."""

    def __init__(self, engine_id: str, generate_fn: Callable[..., str], model: str = ""):
        self.engine_id = engine_id
        self.generate_fn = generate_fn
        self.model = model

    def available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return [self.model] if self.model else []

    def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> EngineResponse:
        prompt = "\n".join(
            f"{message.get('role', 'user')}: {message.get('content', '')}"
            for message in messages
        )
        started = time.perf_counter()
        text = self.generate_fn(prompt, max_tokens=max_tokens) or ""
        return EngineResponse(
            text=text.strip(),
            model=model or self.model,
            engine=self.engine_id,
            prompt_tokens=max(1, len(prompt) // 4),
            completion_tokens=max(1, len(text) // 4),
            latency_seconds=time.perf_counter() - started,
            metadata={"temperature": temperature},
        )

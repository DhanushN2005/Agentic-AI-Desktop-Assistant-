"""Shared inference-engine contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EngineResponse:
    text: str
    model: str = ""
    engine: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class InferenceEngine(ABC):
    engine_id: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """Return True when the engine can serve a request right now."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return model identifiers exposed by this engine."""

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> EngineResponse:
        """Generate one completion for a chat-style message list."""

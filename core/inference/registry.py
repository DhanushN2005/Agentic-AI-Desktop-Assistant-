"""Registry of inference engines, with local-first resolution."""
from __future__ import annotations

from core.inference.base import InferenceEngine
from core.inference.ollama import OllamaEngine


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, InferenceEngine] = {}

    def register(self, engine: InferenceEngine) -> InferenceEngine:
        self._engines[engine.engine_id] = engine
        return engine

    def get(self, engine_id: str) -> InferenceEngine | None:
        return self._engines.get(engine_id)

    def list_engines(self) -> list[str]:
        return sorted(self._engines)

    def resolve(self, preferred: str | None = None) -> InferenceEngine | None:
        if preferred:
            engine = self._engines.get(preferred)
            if engine and engine.available():
                return engine
        local = self._engines.get("ollama")
        if local and local.available():
            return local
        return None


def default_registry() -> EngineRegistry:
    registry = EngineRegistry()
    registry.register(OllamaEngine())
    return registry

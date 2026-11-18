"""Token pricing for cost telemetry.

Cost is an ESTIMATE. Provider prices change and differ by plan, so nothing here is
authoritative:

  1. Local providers (Ollama) cost $0.
  2. If ``FLEXIE_PRICING_FILE`` points at a JSON file, per-model prices from it are used:
         {"gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60}}
     (put your real plan's prices there; model names match by exact name or prefix).
  3. Otherwise a rough blended per-1k-token rate per provider is used (the same
     approximations ``TokenTracker`` in ``core/model_hub.py`` has always used).

Every cost carries a ``source`` ("local" | "override" | "blended") so reports can say how
trustworthy the number is.
"""
from __future__ import annotations

import json
import os
import threading

LOCAL_PROVIDERS = frozenset({"ollama", "local"})

# Rough blended USD per 1k tokens (input + output together). Estimates only.
BLENDED_PER_1K: dict[str, float] = {
    "groq": 0.0001,
    "openai": 0.0015,
    "deepseek": 0.0005,
    "mistral": 0.001,
    "gemini": 0.0005,
    "anthropic": 0.003,
    "ollama": 0.0,
}

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def _overrides() -> dict:
    path = os.getenv("FLEXIE_PRICING_FILE", "")
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
        with _lock:
            cached = _cache.get(path)
            if cached and cached[0] == mtime:
                return cached[1]
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data = data if isinstance(data, dict) else {}
            _cache[path] = (mtime, data)
            return data
    except (OSError, ValueError):
        return {}


def _override_for(model: str) -> dict | None:
    table = _overrides()
    if not table or not model:
        return None
    if model in table and isinstance(table[model], dict):
        return table[model]
    # longest matching prefix wins (e.g. "gpt-4o-mini" for "gpt-4o-mini-2024-07-18")
    matches = [k for k in table if isinstance(table[k], dict) and model.startswith(k)]
    return table[max(matches, key=len)] if matches else None


def cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, str]:
    """Return (estimated cost in USD, source)."""
    provider = (provider or "").lower()
    if provider in LOCAL_PROVIDERS:
        return 0.0, "local"
    override = _override_for(model)
    if override:
        try:
            cost = (prompt_tokens * float(override.get("input_per_1m", 0.0))
                    + completion_tokens * float(override.get("output_per_1m", 0.0))) / 1_000_000
            return cost, "override"
        except (TypeError, ValueError):
            pass
    rate = BLENDED_PER_1K.get(provider, 0.0)
    return (prompt_tokens + completion_tokens) / 1000.0 * rate, "blended"

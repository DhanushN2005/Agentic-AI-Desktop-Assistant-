"""Per-call and per-command LLM usage telemetry (tokens, cost, latency).

Usage:
    with track_llm("groq", model, messages=messages) as call:
        resp = client.chat.completions.create(...)
        call.done(resp.choices[0].message.content, getattr(resp, "usage", None))

Token counts are EXACT when the provider returns usage; otherwise they are estimated
(~4 characters per token) and the call is flagged ``estimated``. Recording never raises:
telemetry must not be able to break a model call. Only successful calls are recorded.

Each call is attributed to the user command in flight (a ``ContextVar`` set by the
orchestrator), so "what did that command cost?" has an answer.
"""
from __future__ import annotations

import contextvars
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from core.telemetry.pricing import cost_usd
from core.telemetry.record import TelemetryRecord

logger = logging.getLogger("Flexie.Usage")

_current_command: contextvars.ContextVar[str | None] = contextvars.ContextVar("flexie_command_id", default=None)
MAX_COMMANDS = 500
MAX_CALLS = 2000


# ------------------------------------------------------------------ token accounting
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def messages_text(messages: list | None) -> str:
    out = []
    for m in messages or []:
        out.append(str(m.get("content", "")) if isinstance(m, dict) else str(m))
    return "\n".join(out)


def _get(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        elif getattr(obj, name, None) is not None:
            return getattr(obj, name)
    return None


def extract_usage(usage: Any) -> tuple[int, int] | None:
    """(prompt_tokens, completion_tokens) from OpenAI/Groq, Anthropic, Gemini or Ollama shapes."""
    if usage is None:
        return None
    prompt = _get(usage, "prompt_tokens", "input_tokens", "prompt_token_count", "prompt_eval_count")
    completion = _get(usage, "completion_tokens", "output_tokens", "candidates_token_count", "eval_count")
    try:
        if prompt is None and completion is None:
            return None
        return int(prompt or 0), int(completion or 0)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------- aggregation
@dataclass
class CommandUsage:
    command_id: str
    query: str = ""
    started: float = field(default_factory=time.time)
    calls: int = 0
    estimated_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    providers: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id, "query": self.query[:120], "calls": self.calls,
            "estimated_calls": self.estimated_calls, "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens, "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6), "latency_seconds": round(self.latency_seconds, 3),
            "providers": dict(self.providers), "started": self.started,
        }


class UsageTracker:
    def __init__(self, persist: bool | None = None, db_path: str | None = None):
        self._lock = threading.RLock()
        self._commands: OrderedDict[str, CommandUsage] = OrderedDict()
        self._calls: deque[dict[str, Any]] = deque(maxlen=MAX_CALLS)
        self._persist = (os.getenv("FLEXIE_USAGE_PERSIST", "1") != "0") if persist is None else persist
        self._db_path = db_path
        self._store = None
        self._store_failed = False

    # -- persistence (best effort) ----------------------------------------------
    def _get_store(self):
        if not self._persist or self._store_failed:
            return None
        if self._store is None:
            try:
                from core.telemetry.store import TelemetryStore

                self._store = TelemetryStore(self._db_path)
            except Exception as e:  # read-only disk etc.: keep going in memory
                self._store_failed = True
                logger.warning("Usage persistence disabled: %s", e)
                return None
        return self._store

    # -- recording ----------------------------------------------------------------
    def record(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int,
               latency_seconds: float, estimated: bool, agent: str = "") -> dict[str, Any]:
        cost, price_source = cost_usd(provider, model, prompt_tokens, completion_tokens)
        command_id = _current_command.get() or ""
        entry = {
            "timestamp": time.time(), "command_id": command_id, "provider": provider, "model": model,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens, "cost_usd": cost,
            "price_source": price_source, "latency_seconds": latency_seconds, "estimated": estimated,
        }
        with self._lock:
            self._calls.append(entry)
            cu = self._commands.get(command_id or "_unattributed")
            if cu is None:
                cu = self._commands[command_id or "_unattributed"] = CommandUsage(command_id or "_unattributed")
                while len(self._commands) > MAX_COMMANDS:
                    self._commands.popitem(last=False)
            cu.calls += 1
            cu.estimated_calls += 1 if estimated else 0
            cu.prompt_tokens += prompt_tokens
            cu.completion_tokens += completion_tokens
            cu.cost_usd += cost
            cu.latency_seconds += latency_seconds
            cu.providers[provider] = cu.providers.get(provider, 0) + 1
        store = self._get_store()
        if store is not None:
            try:
                store.record(TelemetryRecord(
                    model_id=model, engine=provider, agent=agent, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens, latency_seconds=latency_seconds, cost_usd=cost,
                    command_id=command_id,
                    metadata={"estimated": estimated, "price_source": price_source},
                ))
            except Exception as e:
                logger.debug("usage persist failed: %s", e)
        return entry

    # -- reading ------------------------------------------------------------------
    def command(self, command_id: str) -> CommandUsage | None:
        with self._lock:
            return self._commands.get(command_id)

    def recent_commands(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._commands.values())[-limit:]
        return [c.to_dict() for c in reversed(items)]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            calls = list(self._calls)
        by_provider: dict[str, dict[str, Any]] = {}
        for c in calls:
            p = by_provider.setdefault(c["provider"], {"calls": 0, "tokens": 0, "cost_usd": 0.0, "estimated_calls": 0})
            p["calls"] += 1
            p["tokens"] += c["total_tokens"]
            p["cost_usd"] += c["cost_usd"]
            p["estimated_calls"] += 1 if c["estimated"] else 0
        lat = sorted(c["latency_seconds"] for c in calls)

        def pct(q: float) -> float:
            return lat[min(len(lat) - 1, int(q * (len(lat) - 1) + 0.5))] if lat else 0.0

        return {
            "calls": len(calls),
            "estimated_calls": sum(1 for c in calls if c["estimated"]),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            "total_tokens": sum(c["total_tokens"] for c in calls),
            "cost_usd": round(sum(c["cost_usd"] for c in calls), 6),
            "latency_p50_s": round(pct(0.5), 3), "latency_p95_s": round(pct(0.95), 3),
            "per_provider": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in by_provider.items()},
            "note": "Cost is an estimate (see core/telemetry/pricing.py). Calls flagged estimated "
                    "used a ~4 chars/token estimate because the provider returned no usage.",
        }

    def reset(self) -> None:
        with self._lock:
            self._commands.clear()
            self._calls.clear()


_tracker = UsageTracker()


def get_tracker() -> UsageTracker:
    return _tracker


def set_tracker(tracker: UsageTracker) -> UsageTracker:
    """Swap the process-wide tracker (tests). Returns the previous one."""
    global _tracker
    previous, _tracker = _tracker, tracker
    return previous


# ------------------------------------------------------------------ command attribution
def begin_command(command_id: str | None = None) -> contextvars.Token:
    return _current_command.set(command_id or uuid.uuid4().hex[:12])


def end_command(token: contextvars.Token) -> None:
    try:
        _current_command.reset(token)
    except ValueError:  # token from another context; clear instead of raising
        _current_command.set(None)


def current_command() -> str | None:
    return _current_command.get()


def set_command_query(query: str) -> None:
    cid = _current_command.get()
    if cid:
        with _tracker._lock:
            cu = _tracker._commands.setdefault(cid, CommandUsage(cid))
            cu.query = cu.query or query


# --------------------------------------------------------------------------- the hook
class track_llm:  # noqa: N801  (used like a function: ``with track_llm(...) as call``)
    """Context manager that records one successful LLM call."""

    def __init__(self, provider: str, model: str, prompt_text: str = "",
                 messages: list | None = None, agent: str = ""):
        self.provider = provider
        self.model = model or ""
        self.agent = agent
        self._prompt_text = prompt_text or messages_text(messages)
        self._text: str | None = None
        self._usage: Any = None
        self._t0 = 0.0

    def done(self, completion_text: str | None, usage: Any = None) -> None:
        self._text, self._usage = completion_text or "", usage

    def __enter__(self) -> track_llm:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None and self._text is not None:
            try:
                latency = time.perf_counter() - self._t0
                exact = extract_usage(self._usage)
                if exact is not None:
                    prompt, completion, estimated = exact[0], exact[1], False
                else:
                    prompt, completion, estimated = (
                        estimate_tokens(self._prompt_text), estimate_tokens(self._text), True)
                _tracker.record(self.provider, self.model, prompt, completion, latency, estimated, self.agent)
            except Exception as e:  # telemetry must never break the model call
                logger.debug("usage tracking failed: %s", e)
        return False

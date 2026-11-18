"""Run budget + loop guard for autonomous plan execution.

An agent that plans and retries on its own needs hard limits, otherwise a bad plan
(or a model that keeps re-issuing the same step) can run forever, burn LLM calls
and repeat side effects. ``RunBudget`` is charged once per action *attempt*
(retries included) and trips on whichever limit is hit first:

  * step budget      - total attempts
  * time budget      - wall clock since the run started (``expired()`` can also be polled
                       between steps; a single hung step cannot be interrupted from here)
  * loop guard       - the same action repeated back-to-back, a short A,B,A,B cycle, or
                       one action used far too many times overall

Distinct plan steps are never confused with a loop: callers that have a stable step id pass
it as ``key`` so five different "press next" steps are five different actions, while a
retry of one step (same key) counts as a repeat.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("Flexie.RunBudget")

DEFAULT_MAX_STEPS = 20
DEFAULT_MAX_SECONDS = 300.0
DEFAULT_MAX_REPEATS = 3


def _env_positive(name: str, default, cast):
    """Read a positive number from the environment; anything else falls back to the default."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        logger.warning("%s=%r is not a number; using %s", name, raw, default)
        return default
    if value <= 0:
        logger.warning("%s=%r must be > 0; using %s", name, raw, default)
        return default
    return value


@dataclass
class RunBudget:
    max_steps: int = field(default_factory=lambda: _env_positive("FLEXIE_RUN_MAX_STEPS", DEFAULT_MAX_STEPS, int))
    max_seconds: float = field(default_factory=lambda: _env_positive("FLEXIE_RUN_MAX_SECONDS", DEFAULT_MAX_SECONDS, float))
    # The same action may run this many times IN A ROW before it counts as a loop.
    max_repeats: int = field(default_factory=lambda: _env_positive("FLEXIE_RUN_MAX_REPEATS", DEFAULT_MAX_REPEATS, int))
    # Hard ceiling on how often one action may run in total, even if not back-to-back.
    max_total_per_action: int = 0  # 0 -> derived: max(12, 4 * max_repeats)

    steps_used: int = 0
    tripped: str | None = None
    _started: float = field(default_factory=time.monotonic)
    _totals: dict[str, int] = field(default_factory=dict)
    _recent: deque = field(default_factory=lambda: deque(maxlen=12))
    _consecutive: int = 0

    def __post_init__(self) -> None:
        # Direct construction (tests, callers) must be as safe as the env path.
        if not isinstance(self.max_steps, int) or self.max_steps <= 0:
            self.max_steps = DEFAULT_MAX_STEPS
        if not isinstance(self.max_repeats, int) or self.max_repeats <= 0:
            self.max_repeats = DEFAULT_MAX_REPEATS
        if self.max_seconds is None or self.max_seconds != self.max_seconds:  # None / NaN
            self.max_seconds = DEFAULT_MAX_SECONDS
        if not self.max_total_per_action:
            self.max_total_per_action = max(12, 4 * self.max_repeats)

    # ------------------------------------------------------------------ fingerprinting
    @staticmethod
    def fingerprint(tool: str, arguments: dict | None, description: str, key: str | None = None) -> str:
        if key:
            return f"key:{key}"
        try:
            args = json.dumps(arguments or {}, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args = str(arguments)
        desc = "" if tool else (description or "").strip().lower()
        return f"{tool or 'handler'}|{args}|{desc}"

    # --------------------------------------------------------------------------- limits
    def expired(self) -> bool:
        """True (and the budget trips) once the wall-clock limit has passed."""
        if self.tripped:
            return True
        if self.max_seconds is not None and time.monotonic() - self._started > self.max_seconds:
            self.tripped = f"time budget exceeded ({self.max_seconds:.0f}s)"
            return True
        return False

    def _cycle(self) -> bool:
        """True when the recent actions are the same short cycle repeated three times."""
        recent = list(self._recent)
        for period in (2, 3):
            need = period * 3
            if len(recent) >= need:
                tail = recent[-need:]
                if len(set(tail[:period])) == period and tail == tail[:period] * 3:
                    return True
        return False

    def charge(self, tool: str, arguments: dict | None, description: str, key: str | None = None) -> str | None:
        """Account for one attempt. Returns a human-readable reason if the run must stop."""
        if self.tripped:
            return self.tripped
        self.steps_used += 1
        if self.steps_used > self.max_steps:
            self.tripped = f"step budget exceeded ({self.max_steps} actions)"
            return self.tripped
        if self.expired():
            return self.tripped

        fp = self.fingerprint(tool, arguments, description, key)
        label = (description or tool or "action")[:60]
        self._consecutive = self._consecutive + 1 if self._recent and self._recent[-1] == fp else 1
        self._recent.append(fp)
        self._totals[fp] = self._totals.get(fp, 0) + 1

        if self._consecutive > self.max_repeats:
            self.tripped = f"loop detected: the same action ran {self._consecutive - 1} times in a row ({label!r})"
        elif self._cycle():
            self.tripped = f"loop detected: actions are repeating in a cycle ({label!r})"
        elif self._totals[fp] > self.max_total_per_action:
            self.tripped = f"loop detected: one action ran {self._totals[fp] - 1} times in this run ({label!r})"
        return self.tripped

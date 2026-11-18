"""Run budget + loop guard for autonomous plan execution.

An agent that plans and retries on its own needs hard limits, otherwise a bad plan
(or a model that keeps re-issuing the same step) can run forever, burn LLM calls
and repeat side effects. ``RunBudget`` is charged once per action *attempt*
(retries included) and trips on whichever limit is hit first.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field


def _env_num(name: str, default, cast):
    try:
        return cast(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class RunBudget:
    max_steps: int = field(default_factory=lambda: _env_num("FLEXIE_RUN_MAX_STEPS", 20, int))
    max_seconds: float = field(default_factory=lambda: _env_num("FLEXIE_RUN_MAX_SECONDS", 300.0, float))
    # Identical action (same tool+args / same description) allowed this many times per run.
    max_repeats: int = field(default_factory=lambda: _env_num("FLEXIE_RUN_MAX_REPEATS", 3, int))

    steps_used: int = 0
    tripped: str | None = None
    _started: float = field(default_factory=time.monotonic)
    _seen: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def fingerprint(tool: str, arguments: dict | None, description: str) -> str:
        try:
            args = json.dumps(arguments or {}, sort_keys=True, default=str)
        except (TypeError, ValueError):
            args = str(arguments)
        return f"{tool or 'handler'}|{args}|{(description or '').strip().lower() if not tool else ''}"

    def charge(self, tool: str, arguments: dict | None, description: str) -> str | None:
        """Account for one attempt. Returns a human-readable reason if the run must stop."""
        if self.tripped:
            return self.tripped
        self.steps_used += 1
        if self.steps_used > self.max_steps:
            self.tripped = f"step budget exceeded ({self.max_steps} actions)"
        elif time.monotonic() - self._started > self.max_seconds:
            self.tripped = f"time budget exceeded ({self.max_seconds:.0f}s)"
        else:
            fp = self.fingerprint(tool, arguments, description)
            self._seen[fp] = self._seen.get(fp, 0) + 1
            if self._seen[fp] > self.max_repeats:
                self.tripped = (
                    f"loop detected: the same action ran {self._seen[fp] - 1} times "
                    f"({(description or tool)[:60]!r})"
                )
        return self.tripped

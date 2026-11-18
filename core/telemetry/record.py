"""Per-inference telemetry record."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TelemetryRecord:
    model_id: str = ""
    engine: str = ""
    agent: str = ""
    command_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_seconds: float = 0.0
    ttft: float | None = None
    cost_usd: float = 0.0
    energy_joules: float | None = None
    power_watts: float | None = None
    failed: bool = False
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

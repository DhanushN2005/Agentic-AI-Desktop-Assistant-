"""Trace and TraceStep schemas."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepType(str, Enum):
    ROUTE = "route"
    RETRIEVE = "retrieve"
    GENERATE = "generate"
    TOOL_CALL = "tool_call"
    RESPOND = "respond"


@dataclass
class TraceStep:
    step_type: StepType
    timestamp: float = field(default_factory=time.time)
    duration_seconds: float = 0.0
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    query: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent: str = ""
    model: str = ""
    engine: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    result: str = ""
    outcome: str | None = None
    feedback: float | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    total_tokens: int = 0
    total_latency_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: TraceStep) -> None:
        self.steps.append(step)
        self.total_latency_seconds += step.duration_seconds

    def finish(self, result: str = "", outcome: str | None = None) -> None:
        self.result = result
        self.outcome = outcome
        self.ended_at = time.time()

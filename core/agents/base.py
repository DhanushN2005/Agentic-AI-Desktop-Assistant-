"""Typed agent primitives shared by all Flexie agents."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: str = ""
    error: str | None = None


@dataclass
class AgentContext:
    conversation: list[dict[str, Any]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    memory_results: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    content: str
    tool_results: list[ToolResult] = field(default_factory=list)
    turns: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Every agent implements run(input, context) -> AgentResult."""

    agent_id: str = "base"
    accepts_tools: bool = False

    @abstractmethod
    def run(self, input: str, context: AgentContext | None = None) -> AgentResult:
        """Execute the agent on the given input."""

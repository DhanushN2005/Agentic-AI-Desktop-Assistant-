"""
Specialist Agents Architecture — Dodaios-style multi-agent delegation.

Defines specialized agents with scoped permissions and tools:
  - Lead Agent (Jarvis): Goal decomposition, routing, final response synthesis
  - Coder Agent: Workspace files, terminal execution, tests, git
  - Researcher Agent: Browser navigation, scraping, web searches, summarization
  - System Agent: Windows desktop control, window snapping, volume, app operations
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("Flexie.Specialists")


class SpecialistRole(Enum):
    LEAD = "lead"
    CODER = "coder"
    RESEARCHER = "researcher"
    SYSTEM = "system"


class SpecialistAgent:
    """Specialized agent with dedicated prompt, tool scope, and execution loop."""

    def __init__(
        self,
        name: str,
        role: SpecialistRole,
        system_prompt: str,
        tool_tags: list[str],
        tool_registry: Any = None,
        brain: Any = None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.tool_tags = tool_tags
        self.tool_registry = tool_registry
        self.brain = brain

    def get_scoped_tools(self) -> list[str]:
        """Returns the list of tool names this specialist is authorized to use."""
        if not self.tool_registry:
            return []
        tools = []
        for tag in self.tool_tags:
            tools.extend(self.tool_registry.list_tool_names(tag=tag))
        return list(set(tools))

    def run(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Executes a task within the specialist's scope."""
        tools = self.get_scoped_tools()
        prompt = (
            f"{self.system_prompt}\n\n"
            f"Authorized Tools: {', '.join(tools) if tools else 'None'}\n"
            f"Task: {task}\n"
            f"Context: {context or {}}"
        )

        if self.brain and hasattr(self.brain, "ask"):
            try:
                return self.brain.ask(prompt)
            except Exception as e:
                logger.debug(f"[{self.name}] Brain execution failed: {e}")

        return f"[{self.name}] Completed task: {task}"


class AgentTeam:
    """Team coordinator that routes goals between Lead and Specialist agents."""

    def __init__(self, tool_registry: Any = None, brain: Any = None, speak_fn: Callable[[str], None] | None = None):
        self.tool_registry = tool_registry
        self.brain = brain
        self.speak = speak_fn or (lambda msg: None)

        self.coder = SpecialistAgent(
            name="FlexieCoder",
            role=SpecialistRole.CODER,
            system_prompt=(
                "You are Flexie Coder, an expert software engineer agent. "
                "You read, write, patch code, run tests, and manage workspace files precisely."
            ),
            tool_tags=["file", "coding", "terminal", "test", "git"],
            tool_registry=self.tool_registry,
            brain=self.brain,
        )

        self.researcher = SpecialistAgent(
            name="FlexieResearcher",
            role=SpecialistRole.RESEARCHER,
            system_prompt=(
                "You are Flexie Researcher, an autonomous information gathering agent. "
                "You browse web pages, extract summaries, and research technical topics."
            ),
            tool_tags=["browser", "search", "comm"],
            tool_registry=self.tool_registry,
            brain=self.brain,
        )

        self.system = SpecialistAgent(
            name="FlexieSystem",
            role=SpecialistRole.SYSTEM,
            system_prompt=(
                "You are Flexie System, the Windows OS automation specialist. "
                "You control applications, arrange windows, adjust audio/brightness, and manage processes."
            ),
            tool_tags=["system", "desktop"],
            tool_registry=self.tool_registry,
            brain=self.brain,
        )

        self.lead = SpecialistAgent(
            name="FlexieLead",
            role=SpecialistRole.LEAD,
            system_prompt=(
                "You are Flexie Lead, the central orchestrator. "
                "Decompose complex user goals and delegate to Coder, Researcher, or System specialists."
            ),
            tool_tags=["system", "browser", "coding", "file"],
            tool_registry=self.tool_registry,
            brain=self.brain,
        )

    def route_task(self, goal: str) -> SpecialistAgent:
        """Determines the best specialist for a given user goal."""
        low = goal.lower()
        if any(w in low for w in ["code", "script", "test", "git", "file", "write function", "debug", "refactor"]):
            return self.coder
        elif any(w in low for w in ["research", "search web", "browse", "lookup", "scrape", "summarize article"]):
            return self.researcher
        elif any(w in low for w in ["volume", "brightness", "window", "snap", "app", "close", "launch", "kill process"]):
            return self.system
        return self.lead

    def delegate(self, goal: str, context: dict[str, Any] | None = None) -> str:
        """Delegates a goal to the appropriate specialist agent."""
        specialist = self.route_task(goal)
        logger.info(f"[AgentTeam] Delegating goal '{goal[:50]}' to {specialist.name}")
        return specialist.run(goal, context)

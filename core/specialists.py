"""
Specialist Agents — scoped, tool-using agents with delegation.

  - Lead:       decomposes a goal and delegates to specialists (virtual ``delegate`` tool)
  - Coder:      workspace files, terminal, tests, git, python
  - Researcher: browser navigation / search / extraction
  - System:     application control

Each specialist is a ``ToolUsingAgent`` over a ``ScopedToolRegistry``: tools outside its
scope are neither shown to the model nor executable. Permission-gated tools ask the user
for approval (voice or UI) instead of silently failing, and every run has a step budget
and a repeated-call loop guard.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from enum import Enum
from typing import Any

from core.action_result import ActionResult
from core.tool_registry import PermissionLevel, ToolSchema, ToolSpec

logger = logging.getLogger("Flexie.Specialists")

MAX_DELEGATIONS_PER_RUN = 3


class SpecialistRole(Enum):
    LEAD = "lead"
    CODER = "coder"
    RESEARCHER = "researcher"
    SYSTEM = "system"


class SpecialistAgent:
    """A role with its own prompt, hard tool scope and tool-calling loop."""

    def __init__(
        self,
        name: str,
        role: SpecialistRole,
        system_prompt: str,
        tool_tags: list[str],
        tool_registry: Any = None,
        brain: Any = None,
        generate: Any = None,
        max_turns: int = 6,
        permission_system: Any = None,
        voice: Any = None,
        approval_wait_seconds: float = 20.0,
        tool_names: list[str] | None = None,
    ):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.tool_tags = tool_tags
        # Exact tool names are the strict way to scope; tags are the broad way.
        self.tool_names = list(tool_names or [])
        self.tool_registry = tool_registry
        self.brain = brain
        self.generate = generate
        self.max_turns = max_turns
        self.permission_system = permission_system
        self.voice = voice
        self.approval_wait_seconds = approval_wait_seconds

    def get_scoped_tools(self) -> list[str]:
        """Names of the registered tools this specialist is authorized to use."""
        if not self.tool_registry:
            return []
        tools: set[str] = {n for n in self.tool_names if self.tool_registry.get(n) is not None}
        for tag in self.tool_tags:
            tools.update(self.tool_registry.list_tool_names(tag=tag))
        return sorted(tools)

    def _generate_fn(self):
        if self.generate:
            return self.generate
        if self.brain is not None and hasattr(self.brain, "ask"):
            from core.agents.brain_generate import make_brain_generate

            return make_brain_generate(self.brain)
        return None

    def _authorizer(self):
        ps = self.permission_system
        if ps is None:
            return None, None

        def authorize(tool_name: str, args: dict, reason: str) -> bool:
            spec = self.tool_registry.get(tool_name) if self.tool_registry else None
            level = spec.permission if spec is not None else PermissionLevel.USER_CONFIRMATION
            return ps.await_approval(
                tool_name, f"run {tool_name} {args}", level,
                voice_confirm=getattr(self.voice, "confirm", None),
                wait_seconds=self.approval_wait_seconds,
            )

        return authorize, ps.consume_approval

    def run(self, task: str, context: dict[str, Any] | None = None,
            extra_tools: dict[str, ToolSpec] | None = None) -> str:
        """Run a task inside this specialist's scope; returns the final reply text."""
        generate = self._generate_fn()
        if generate is None:
            return f"[{self.name}] No model available to complete: {task}"

        from core.agents import AgentContext, ScopedToolRegistry, ToolUsingAgent

        scoped_names = self.get_scoped_tools()
        scoped = ScopedToolRegistry(self.tool_registry, scoped_names, extra=extra_tools)
        authorize, consume = self._authorizer()
        loop = ToolUsingAgent(
            agent_id=self.name,
            generate=generate,
            tool_registry=scoped,
            max_turns=self.max_turns,
            system_prompt=self.system_prompt,
            authorizer=authorize,
            on_authorized=consume,
        )
        agent_context = AgentContext(tools=sorted(scoped.allowed), metadata=context or {})
        result = loop.run(task, agent_context)
        if result.metadata.get("budget_tripped"):
            logger.warning("[%s] stopped: %s", self.name, result.metadata["budget_tripped"])
        return result.content


# Word-boundary keyword scoring (substring matching sent "apple" to the System agent).
_ROUTES: list[tuple[SpecialistRole, re.Pattern]] = [
    (SpecialistRole.CODER, re.compile(
        r"\b(code|coding|script|test|tests|unit test|git|commit|file|files|function|debug|"
        r"refactor|python|bug|compile|repo|repository|patch)\b", re.I)),
    (SpecialistRole.RESEARCHER, re.compile(
        r"\b(research|search the web|search web|browse|lookup|look up|scrape|website|"
        r"summarize article|investigate|find out)\b", re.I)),
    (SpecialistRole.SYSTEM, re.compile(
        r"\b(volume|brightness|window|windows|snap|app|apps|application|launch|open|close|"
        r"kill process|minimize|maximize)\b", re.I)),
]


class AgentTeam:
    """Routes goals to the right specialist; the lead can delegate sub-tasks."""

    def __init__(
        self,
        tool_registry: Any = None,
        brain: Any = None,
        speak_fn: Callable[[str], None] | None = None,
        permission_system: Any = None,
        voice: Any = None,
    ):
        self.tool_registry = tool_registry
        self.brain = brain
        self.speak = speak_fn or (lambda msg: None)
        common = dict(tool_registry=tool_registry, brain=brain, permission_system=permission_system, voice=voice)

        # Tags match the tags tools are actually registered with (code, file, git, terminal,
        # test, python, browser, search, web, extract, app, email, communication).
        self.coder = SpecialistAgent(
            name="FlexieCoder", role=SpecialistRole.CODER,
            system_prompt=(
                "You are Flexie Coder, an expert software engineer agent. Read code before "
                "changing it, make minimal precise edits, run tests to verify, and report what you did."
            ),
            tool_tags=["code", "file", "git", "terminal", "test", "python"], **common,
        )
        self.researcher = SpecialistAgent(
            name="FlexieResearcher", role=SpecialistRole.RESEARCHER,
            system_prompt=(
                "You are Flexie Researcher, an information-gathering agent. Search, open pages, "
                "extract what matters, and answer concisely with what you found."
            ),
            tool_tags=[],
            tool_names=["browser_search", "browser_navigate", "browser_extract", "browser_click", "browser_fill"],
            **common,
        )
        self.system = SpecialistAgent(
            name="FlexieSystem", role=SpecialistRole.SYSTEM,
            system_prompt=(
                "You are Flexie System, the desktop automation specialist. You open and manage "
                "applications. Do exactly what was asked and confirm the result."
            ),
            tool_tags=[], tool_names=["app.open"], **common,
        )
        self.lead = SpecialistAgent(
            name="FlexieLead", role=SpecialistRole.LEAD,
            system_prompt=(
                "You are Flexie Lead, the central orchestrator. Answer simple questions "
                "directly. For work that needs tools, use the `delegate` tool to hand a "
                "focused sub-task to the coder, researcher or system specialist, then "
                "combine their results into one final reply."
            ),
            tool_tags=[], tool_names=["email_read_unread", "email_send", "email_reply"], **common,
        )
        self._by_role = {s.role: s for s in (self.coder, self.researcher, self.system, self.lead)}

    # ------------------------------------------------------------------ routing
    def route_task(self, goal: str) -> SpecialistAgent:
        """Pick the specialist whose keywords match the goal most; ties favour coder > researcher > system."""
        best_role, best_hits = SpecialistRole.LEAD, 0
        for role, pattern in _ROUTES:
            hits = len(pattern.findall(goal))
            if hits > best_hits:
                best_role, best_hits = role, hits
        return self._by_role[best_role]

    # --------------------------------------------------------------- delegation
    def _delegate_tool(self, context: dict[str, Any] | None) -> ToolSpec:
        used = [0]

        def _delegate(role: str, task: str) -> ActionResult:
            if used[0] >= MAX_DELEGATIONS_PER_RUN:
                return ActionResult.fail(message="Delegation limit reached for this request.", intent="delegate")
            try:
                target = self._by_role[SpecialistRole(role)]
            except ValueError:
                return ActionResult.fail(message=f"Unknown role '{role}'.", intent="delegate")
            if target.role == SpecialistRole.LEAD:
                return ActionResult.fail(message="The lead cannot delegate to itself.", intent="delegate")
            used[0] += 1
            logger.info("[AgentTeam] lead -> %s: %s", target.name, task[:60])
            return ActionResult.ok(message=target.run(task, context), intent="delegate")

        return ToolSpec(
            name="delegate",
            description="Hand a focused sub-task to a specialist and get its result back.",
            params=[
                ToolSchema("role", "str", True, description="coder | researcher | system",
                           enum=["coder", "researcher", "system"]),
                ToolSchema("task", "str", True, description="What the specialist should do"),
            ],
            permission=PermissionLevel.READ_ONLY,  # the specialist's own tools are still gated
            execute_fn=_delegate,
            timeout=300,
            tags=["delegate"],
        )

    def delegate(self, goal: str, context: dict[str, Any] | None = None) -> str:
        """Run a goal on the best-fit specialist (the lead may fan out to others)."""
        specialist = self.route_task(goal)
        logger.info("[AgentTeam] Delegating goal '%s' to %s", goal[:50], specialist.name)
        extra = {"delegate": self._delegate_tool(context)} if specialist.role == SpecialistRole.LEAD else None
        return specialist.run(goal, context, extra_tools=extra)

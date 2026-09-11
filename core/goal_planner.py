"""
Goal Planner — decomposes natural-language goals into structured task graphs.

Unlike the existing WorkflowParser (which handles simple "A and B" compounds)
and DAGPlanner (which executes pre-defined task graphs), the Goal Planner:

1. Takes a free-form natural-language goal
2. Uses LLM to decompose it into structured steps
3. Each step contains: task_id, description, tool, arguments, dependencies,
   status, result, error, retry_count, verification
4. Resolves tool dependencies (e.g., "search files" before "rename file")
5. Produces a TaskGraph that the AgentExecutor can consume

This sits ABOVE the existing deterministic routing system.
Simple commands still go through the fast router.
Complex/ambiguous goals get escalated to the GoalPlanner.
"""
import json
import logging
import uuid
from enum import Enum, auto
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from core.action_result import ActionResult


class StepStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    SKIPPED = auto()
    WAITING_CONFIRM = auto()


class VerificationStrategy(Enum):
    NONE = auto()
    FILE_EXISTS = auto()
    APP_RUNNING = auto()
    PAGE_LOADED = auto()
    CLIPBOARD_CHANGED = auto()
    DOM_ELEMENT = auto()
    CUSTOM = auto()


@dataclass
class TaskStep:
    """A single step in a decomposed goal plan."""
    task_id: str
    description: str
    tool: str  # tool name from ToolRegistry, or "" for conversational steps
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # task_ids this step depends on
    status: StepStatus = StepStatus.PENDING
    result: Optional[ActionResult] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    verification: VerificationStrategy = VerificationStrategy.NONE
    verification_args: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 15.0
    permission_level: str = "SAFE_ACTION"
    requires_confirmation: bool = False
    human_fallback: str = ""  # message to show if all retries fail

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "tool": self.tool,
            "arguments": self.arguments,
            "depends_on": self.depends_on,
            "status": self.status.name,
            "retry_count": self.retry_count,
            "verification": self.verification.name,
            "timeout": self.timeout,
            "permission_level": self.permission_level,
            "requires_confirmation": self.requires_confirmation,
        }

    def is_ready(self, completed: set) -> bool:
        """Check if all dependencies are satisfied."""
        return all(dep in completed for dep in self.depends_on)

    def mark_running(self):
        self.status = StepStatus.RUNNING

    def mark_completed(self, result: ActionResult):
        self.status = StepStatus.COMPLETED
        self.result = result

    def mark_failed(self, error: str):
        self.status = StepStatus.FAILED
        self.error = error

    def mark_cancelled(self):
        self.status = StepStatus.CANCELLED

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def increment_retry(self):
        self.retry_count += 1


@dataclass
class TaskGraph:
    """A complete decomposed goal plan."""
    goal_id: str
    original_goal: str
    steps: List[TaskStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False

    def add_step(self, step: TaskStep):
        self.steps.append(step)

    def get_step(self, task_id: str) -> Optional[TaskStep]:
        for s in self.steps:
            if s.task_id == task_id:
                return s
        return None

    def get_ready_steps(self) -> List[TaskStep]:
        """Get steps whose dependencies are all completed."""
        completed = {
            s.task_id for s in self.steps
            if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
        }
        return [
            s for s in self.steps
            if s.status == StepStatus.PENDING and s.is_ready(completed)
        ]

    def all_completed(self) -> bool:
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.CANCELLED)
            for s in self.steps
        )

    def has_failures(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def summary(self) -> str:
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        running = sum(1 for s in self.steps if s.status == StepStatus.RUNNING)
        return f"Goal: {self.original_goal[:60]}... | {done}/{total} done, {running} running, {failed} failed"

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "original_goal": self.original_goal,
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
            "cancelled": self.cancelled,
        }


class GoalPlanner:
    """
    Decomposes natural-language goals into structured TaskGraphs.

    Uses LLM for decomposition, but the actual tool mapping is deterministic
    based on the ToolRegistry.
    """

    # Mapping of common verb phrases to tool names
    TOOL_KEYWORDS = {
        "search": "files.search",
        "find": "files.search",
        "rename": "files.rename",
        "move": "files.move",
        "copy": "files.copy",
        "delete": "files.delete",
        "create": "files.create",
        "open": "app.open",
        "launch": "app.open",
        "close": "app.close",
        "screenshot": "vision.screenshot",
        "analyze screen": "vision.analyze",
        "read pdf": "pdf.read",
        "summarize": "text.summarize",
        "translate": "text.translate",
        "weather": "weather.get",
        "news": "news.get",
        "joke": "jokes.get",
        "quote": "quotes.get",
        "define": "dictionary.define",
        "wikipedia": "wiki.search",
        "web search": "browser.search",
        "google": "browser.search",
        "email": "email.compose",
        "git": "terminal.run",
        "run": "terminal.run",
        "execute": "terminal.run",
        "echo": "test.echo",
    }

    def __init__(self, brain=None, tool_registry=None):
        self.brain = brain
        self.tool_registry = tool_registry
        self.logger = logging.getLogger("Flexie.GoalPlanner")

    def decompose(self, goal: str, context: str = "") -> TaskGraph:
        """
        Decompose a natural-language goal into a TaskGraph.

        For simple goals (single action), returns a graph with one step.
        For complex goals (multi-action), uses LLM to break them down.
        """
        goal_id = str(uuid.uuid4())[:8]

        # Try LLM decomposition for complex goals
        if self.brain and self._is_complex(goal):
            try:
                return self._llm_decompose(goal, goal_id, context)
            except Exception as e:
                self.logger.warning(f"[GOAL_PLANNER] LLM decomposition failed: {e}. Falling back to deterministic.")

        # Deterministic decomposition
        return self._deterministic_decompose(goal, goal_id)

    def _is_complex(self, goal: str) -> bool:
        """Determine if a goal requires LLM decomposition."""
        # Multi-action indicators
        indicators = [" and ", " then ", " after ", " before ", " so that ",
                      ", ", "also", "then", "next", "finally"]
        return any(ind in goal.lower() for ind in indicators)

    def _deterministic_decompose(self, goal: str, goal_id: str) -> TaskGraph:
        """Simple deterministic decomposition without LLM."""
        graph = TaskGraph(goal_id=goal_id, original_goal=goal)

        # Try to split on "and", "then", commas
        import re
        parts = re.split(r",\s*(?:and\s+|then\s+)?|\s+(?:and|then)\s+", goal.lower())
        parts = [p.strip() for p in parts if len(p.strip()) > 2]

        if not parts:
            parts = [goal]

        for i, part in enumerate(parts):
            tool = self._match_tool(part)
            step = TaskStep(
                task_id=f"step_{i}",
                description=part,
                tool=tool,
                depends_on=[f"step_{i-1}"] if i > 0 else [],
                verification=self._infer_verification(part),
            )
            graph.add_step(step)

        return graph

    def _llm_decompose(self, goal: str, goal_id: str, context: str = "") -> TaskGraph:
        """Use LLM to decompose a complex goal."""
        # Get available tools
        available_tools = []
        if self.tool_registry:
            available_tools = self.tool_registry.list_tool_names()

        tools_str = ", ".join(available_tools[:50]) if available_tools else "(use existing handlers)"

        prompt = f"""You are a task planner for a desktop AI assistant.
Decompose the user's goal into sequential steps.

User Goal: "{goal}"
Context: {context or "None"}

Available Tools: {tools_str}

Return ONLY a JSON array of steps. Each step:
{{
  "description": "clear description of what to do",
  "tool": "tool_name or empty string for conversational",
  "arguments": {{}},
  "verification": "NONE|FILE_EXISTS|APP_RUNNING|PAGE_LOADED",
  "timeout": 15,
  "permission_level": "READ_ONLY|SAFE_ACTION|USER_CONFIRMATION|SENSITIVE|DANGEROUS",
  "requires_confirmation": false
}}

Rules:
- Each step must be ONE clear action
- Steps should be SHORT (under 10 words each)
- Order steps by dependency (A before B)
- Use verification for file/app operations
- Set permission_level based on risk
- Return ONLY the JSON array, no other text"""

        try:
            response = self.brain.ask(prompt, system_override="You are a precise task planner. Return ONLY valid JSON.")
            # Extract JSON array
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                steps_data = json.loads(match.group())
                graph = TaskGraph(goal_id=goal_id, original_goal=goal)

                for i, step_data in enumerate(steps_data):
                    verification_str = step_data.get("verification", "NONE")
                    try:
                        verification = VerificationStrategy[verification_str]
                    except KeyError:
                        verification = VerificationStrategy.NONE

                    step = TaskStep(
                        task_id=f"step_{i}",
                        description=step_data.get("description", ""),
                        tool=step_data.get("tool", ""),
                        arguments=step_data.get("arguments", {}),
                        depends_on=[f"step_{i-1}"] if i > 0 else [],
                        verification=verification,
                        timeout=step_data.get("timeout", 15.0),
                        permission_level=step_data.get("permission_level", "SAFE_ACTION"),
                        requires_confirmation=step_data.get("requires_confirmation", False),
                    )
                    graph.add_step(step)

                return graph
        except Exception as e:
            self.logger.warning(f"[GOAL_PLANNER] LLM parse error: {e}")

        # Fallback to deterministic
        return self._deterministic_decompose(goal, goal_id)

    def _match_tool(self, description: str) -> str:
        """Match a step description to a tool name."""
        desc_lower = description.lower()
        for keyword, tool in self.TOOL_KEYWORDS.items():
            if keyword in desc_lower:
                return tool
        return ""

    def _infer_verification(self, description: str) -> VerificationStrategy:
        """Infer appropriate verification strategy from description."""
        desc_lower = description.lower()
        if any(w in desc_lower for w in ["create", "rename", "move", "write", "save"]):
            return VerificationStrategy.FILE_EXISTS
        if any(w in desc_lower for w in ["open", "launch", "run"]):
            return VerificationStrategy.APP_RUNNING
        if any(w in desc_lower for w in ["navigate", "browse", "go to"]):
            return VerificationStrategy.PAGE_LOADED
        return VerificationStrategy.NONE

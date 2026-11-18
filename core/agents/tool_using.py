"""Multi-turn tool-calling agent loop."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from core.agents.base import AgentContext, AgentResult, BaseAgent, ToolResult
from core.run_budget import RunBudget

MAX_TOOL_OUTPUT_CHARS = 4000


class ToolUsingAgent(BaseAgent):
    """Agent that calls a generate function and executes returned tool calls.

    ``generate(messages, tools=...)`` must return either a string or a dict with
    ``content`` and optional ``tool_calls`` (OpenAI function-calling shape).

    Safety/robustness:
      * every tool call is charged to a ``RunBudget`` (step cap + identical-call loop guard)
      * ``authorizer(tool_name, args, reason) -> bool`` is asked when the registry denies a
        call for permission reasons; the call is retried once only on an explicit approval
      * tool output is truncated before it is fed back to the model
    """

    accepts_tools = True

    def __init__(
        self,
        agent_id: str,
        generate: Callable[..., Any],
        tool_registry: Any = None,
        max_turns: int = 5,
        system_prompt: str = "You are a tool-using agent. Use tools when needed.",
        authorizer: Callable[[str, dict, str], bool] | None = None,
        on_authorized: Callable[[], None] | None = None,
        max_tool_calls: int | None = None,
        max_repeats: int = 2,
    ):
        self.agent_id = agent_id
        self.generate = generate
        self.tool_registry = tool_registry
        self.max_turns = max_turns
        self.system_prompt = system_prompt
        self.authorizer = authorizer
        self.on_authorized = on_authorized
        self.max_tool_calls = max_tool_calls if max_tool_calls is not None else max_turns * 3
        self.max_repeats = max_repeats

    def _tool_schemas(self) -> list[dict]:
        if not self.tool_registry:
            return []
        list_tools = getattr(self.tool_registry, "list_tools", None)
        if not list_tools:
            return []
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema_dict(),
            }
            for tool in list_tools()
        ]

    def _execute(self, name: str, args: dict) -> ToolResult:
        if not self.tool_registry:
            return ToolResult(name, False, error="no tool registry")
        execute = getattr(self.tool_registry, "execute", None)
        if not execute:
            return ToolResult(name, False, error="registry has no execute()")
        try:
            result = execute(name, args)
            if (
                not getattr(result, "success", True)
                and (getattr(result, "data", None) or {}).get("permission_denied")
                and self.authorizer is not None
            ):
                reason = str(getattr(result, "message", "permission required"))
                if self.authorizer(name, args, reason):
                    try:
                        result = execute(name, args)
                    finally:
                        if self.on_authorized:
                            self.on_authorized()  # one approval covers this one call only
            success = bool(getattr(result, "success", False))
            output = str(getattr(result, "message", result))
            return ToolResult(name, success, output=output[:MAX_TOOL_OUTPUT_CHARS])
        except Exception as exc:  # tool failures must not kill the loop
            return ToolResult(name, False, error=str(exc))

    def run(self, input: str, context: AgentContext | None = None) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.extend(context.conversation)
        messages.append({"role": "user", "content": input})

        budget = RunBudget(max_steps=self.max_tool_calls, max_repeats=self.max_repeats)
        results: list[ToolResult] = []
        content = ""
        for turn in range(1, self.max_turns + 1):
            response = self.generate(messages, tools=self._tool_schemas())
            if isinstance(response, str):
                return AgentResult(response, results, turn)

            content = response.get("content", "") or ""
            calls = response.get("tool_calls") or []
            if not calls:
                return AgentResult(content, results, turn)

            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            for call in calls:
                function = call.get("function", call)
                name = function.get("name", "")
                args = function.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                args = args if isinstance(args, dict) else {}

                tripped = budget.charge(name, args, "")
                if tripped:
                    result = ToolResult(name, False, error=f"stopped: {tripped}")
                    results.append(result)
                    return AgentResult(
                        content=f"I stopped because {tripped}.",
                        tool_results=results,
                        turns=turn,
                        metadata={"budget_tripped": tripped},
                    )
                result = self._execute(name, args)
                results.append(result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", name),
                        "content": result.output or result.error or "",
                    }
                )

        return AgentResult(
            content=content or "Max turns reached.",
            tool_results=results,
            turns=self.max_turns,
            metadata={"max_turns_exceeded": True},
        )

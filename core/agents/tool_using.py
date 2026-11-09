"""Multi-turn tool-calling agent loop."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.agents.base import AgentContext, AgentResult, BaseAgent, ToolResult


class ToolUsingAgent(BaseAgent):
    """Agent that calls a generate function and executes returned tool calls.

    ``generate(messages, tools=...)`` must return either a string or a dict with
    ``content`` and optional ``tool_calls`` (OpenAI function-calling shape).
    """

    accepts_tools = True

    def __init__(
        self,
        agent_id: str,
        generate: Callable[..., Any],
        tool_registry: Any = None,
        max_turns: int = 5,
        system_prompt: str = "You are a tool-using agent. Use tools when needed.",
    ):
        self.agent_id = agent_id
        self.generate = generate
        self.tool_registry = tool_registry
        self.max_turns = max_turns
        self.system_prompt = system_prompt

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
            success = bool(getattr(result, "success", False))
            output = str(getattr(result, "message", result))
            return ToolResult(name, success, output=output)
        except Exception as exc:  # tool failures must not kill the loop
            return ToolResult(name, False, error=str(exc))

    def run(self, input: str, context: AgentContext | None = None) -> AgentResult:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.extend(context.conversation)
        messages.append({"role": "user", "content": input})

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
                    import json

                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = self._execute(name, args if isinstance(args, dict) else {})
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

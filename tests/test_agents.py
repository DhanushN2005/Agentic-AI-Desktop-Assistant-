from types import SimpleNamespace

from core.agents import AgentContext, AgentRegistry, ToolUsingAgent


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def list_tools(self):
        return []

    def execute(self, name, args):
        self.calls.append((name, args))
        return SimpleNamespace(success=True, message="tool ok")


def test_tool_using_agent_executes_tool_then_answers():
    registry = FakeRegistry()
    responses = [
        {
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "calculator", "arguments": {"expr": "2+2"}}}
            ],
        },
        {"content": "The answer is 4.", "tool_calls": []},
    ]

    def generate(messages, tools=None):
        return responses.pop(0)

    agent = ToolUsingAgent("orchestrator", generate, tool_registry=registry, max_turns=3)
    result = agent.run("What is 2+2?")

    assert result.content == "The answer is 4."
    assert result.turns == 2
    assert result.tool_results[0].tool_name == "calculator"
    assert result.tool_results[0].success is True
    assert registry.calls == [("calculator", {"expr": "2+2"})]


def test_tool_using_agent_respects_max_turns():
    registry = FakeRegistry()

    def generate(messages, tools=None):
        return {
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "loop", "arguments": {}}}],
        }

    agent = ToolUsingAgent("looper", generate, tool_registry=registry, max_turns=2)
    result = agent.run("loop")
    assert result.turns == 2
    assert result.metadata["max_turns_exceeded"] is True


def test_agent_registry_roundtrip():
    registry = AgentRegistry()
    agent = ToolUsingAgent("simple", lambda messages, tools=None: "hi")
    registry.register(agent)
    assert registry.get("simple") is agent
    assert registry.list_agents() == ["simple"]


def test_context_is_prepended():
    seen = {}

    def generate(messages, tools=None):
        seen["messages"] = messages
        return "ok"

    context = AgentContext(conversation=[{"role": "user", "content": "earlier"}])
    ToolUsingAgent("ctx", generate).run("now", context)
    assert seen["messages"][1]["content"] == "earlier"

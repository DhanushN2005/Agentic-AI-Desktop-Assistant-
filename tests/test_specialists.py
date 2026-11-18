from unittest.mock import MagicMock

from core.action_result import ActionResult
from core.specialists import AgentTeam, SpecialistAgent, SpecialistRole
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec


def test_specialist_tool_scoping():
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="file_read",
        description="Read file",
        params=[ToolSchema(name="path", type="str")],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=lambda path: ActionResult.ok("content"),
        tags=["file", "coding"],
    ))
    registry.register(ToolSpec(
        name="browser_search",
        description="Search web",
        params=[ToolSchema(name="query", type="str")],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=lambda query: ActionResult.ok("results"),
        tags=["browser", "search"],
    ))

    coder = SpecialistAgent(
        name="Coder",
        role=SpecialistRole.CODER,
        system_prompt="You code.",
        tool_tags=["file", "coding"],
        tool_registry=registry,
    )
    tools = coder.get_scoped_tools()
    assert "file_read" in tools
    assert "browser_search" not in tools


def test_agent_team_routing():
    team = AgentTeam()

    coder_agent = team.route_task("write a python script to parse logs")
    assert coder_agent.role == SpecialistRole.CODER

    researcher_agent = team.route_task("research quantum computing advancements")
    assert researcher_agent.role == SpecialistRole.RESEARCHER

    system_agent = team.route_task("snap window left and set volume to 50")
    assert system_agent.role == SpecialistRole.SYSTEM

    lead_agent = team.route_task("what is your plan for today?")
    assert lead_agent.role == SpecialistRole.LEAD


def test_agent_team_delegate():
    mock_brain = MagicMock()
    mock_brain.ask.return_value = "Specialist execution finished successfully."

    team = AgentTeam(brain=mock_brain)
    result = team.delegate("write a unit test for memory manager")

    assert "Specialist execution finished successfully." in result
    assert mock_brain.ask.called


def test_specialist_uses_tool_loop_when_generate_supplied():
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="file_read",
        description="Read file",
        params=[ToolSchema(name="path", type="str")],
        permission=PermissionLevel.READ_ONLY,
        execute_fn=lambda path: ActionResult.ok("content"),
        tags=["file"],
    ))
    responses = [
        {"content": "", "tool_calls": [
            {"id": "1", "function": {"name": "file_read", "arguments": {"path": "a.txt"}}}
        ]},
        {"content": "read done", "tool_calls": []},
    ]
    coder = SpecialistAgent(
        name="Coder",
        role=SpecialistRole.CODER,
        system_prompt="You code.",
        tool_tags=["file"],
        tool_registry=registry,
        generate=lambda messages, tools=None: responses.pop(0),
    )
    assert coder.run("read a.txt") == "read done"


def test_capability_delegation_to_specialist():
    from core.capability_registry import CapabilityRegistry
    from core.handlers.agents import handle_capability_delegation

    mock_orch = MagicMock()
    mock_orch.capability_registry = CapabilityRegistry()
    mock_orch.agent_team = MagicMock()
    from core.agents import AgentResult
    mock_orch.get_conversation_history.return_value = [{"role": "user", "content": "earlier"}]
    mock_orch.agent_team.delegate_full.return_value = AgentResult("Delegated task completed.")

    handled = handle_capability_delegation(mock_orch, "specialist", "delegate research task", silent=False)
    assert handled is True
    args, kwargs = mock_orch.agent_team.delegate_full.call_args
    assert args == ("delegate research task",)
    assert kwargs["history"] == [{"role": "user", "content": "earlier"}]   # follow-up context is passed on
    mock_orch.speak.assert_called_with("Delegated task completed.")


def test_delegation_reports_a_cut_short_run_as_not_handled():
    """A specialist that hit its limits must not look like a normal answer (and an empty reply falls through)."""
    from core.agents import AgentResult
    from core.capability_registry import CapabilityRegistry
    from core.handlers.agents import handle_capability_delegation

    orch = MagicMock()
    orch.capability_registry = CapabilityRegistry()
    orch.agent_team = MagicMock()
    orch.agent_team.delegate_full.return_value = AgentResult("I stopped because loop detected.",
                                                              metadata={"budget_tripped": "loop detected"})
    assert handle_capability_delegation(orch, "specialist", "do things", silent=False) is False
    orch.speak.assert_called_with("I stopped because loop detected.")   # the user is still told

    orch2 = MagicMock()
    orch2.capability_registry = CapabilityRegistry()
    orch2.agent_team = MagicMock()
    orch2.agent_team.delegate_full.return_value = AgentResult("   ")
    assert handle_capability_delegation(orch2, "specialist", "do things", silent=False) is False
    orch2.speak.assert_not_called()

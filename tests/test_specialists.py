import pytest
from unittest.mock import MagicMock
from core.specialists import AgentTeam, SpecialistAgent, SpecialistRole
from core.tool_registry import ToolRegistry, ToolSpec, ToolSchema, PermissionLevel
from core.action_result import ActionResult


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


def test_capability_delegation_to_specialist():
    from core.capability_registry import CapabilityRegistry
    from core.handlers.agents import handle_capability_delegation

    mock_orch = MagicMock()
    mock_orch.capability_registry = CapabilityRegistry()
    mock_orch.agent_team = MagicMock()
    mock_orch.agent_team.delegate.return_value = "Delegated task completed."

    handled = handle_capability_delegation(mock_orch, "specialist", "delegate research task", silent=False)
    assert handled is True
    mock_orch.agent_team.delegate.assert_called_with("delegate research task")
    mock_orch.speak.assert_called_with("Delegated task completed.")

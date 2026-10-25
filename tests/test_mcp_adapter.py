"""Tests for Step 3: MCP (Model Context Protocol) Client Adapter."""
import json
import pytest
from unittest.mock import MagicMock, patch

from core.mcp_adapter import MCPServerConfig, MCPStdioClient, MCPManager
from core.tool_registry import ToolRegistry, PermissionLevel
from core.action_result import ActionResult


class TestMCPAdapter:
    def test_mcp_server_config_serialization(self):
        cfg = MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "C:\\temp"],
            env={"NODE_ENV": "production"},
            timeout=15.0,
        )
        d = cfg.to_dict()
        assert d["name"] == "filesystem"
        assert d["command"] == "npx"
        assert d["timeout"] == 15.0

        recovered = MCPServerConfig.from_dict(d)
        assert recovered.name == cfg.name
        assert recovered.args == cfg.args
        assert recovered.env == cfg.env

    def test_adapt_mcp_tool_to_spec(self):
        registry = ToolRegistry()
        manager = MCPManager(registry)
        mock_client = MagicMock()
        mock_client.config = MCPServerConfig(name="test_server", command="test")

        mcp_tool = {
            "name": "read_file",
            "description": "Read file contents from disk",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to file"},
                    "max_lines": {"type": "integer", "description": "Maximum lines to read", "default": 100},
                },
                "required": ["path"],
            },
        }

        spec = manager._adapt_mcp_tool_to_spec("test_server", mock_client, mcp_tool)
        assert spec is not None
        assert spec.name == "mcp_test_server_read_file"
        assert "[test_server] Read file contents from disk" in spec.description
        assert len(spec.params) == 2

        path_param = next(p for p in spec.params if p.name == "path")
        assert path_param.type == "str"
        assert path_param.required is True

        lines_param = next(p for p in spec.params if p.name == "max_lines")
        assert lines_param.type == "int"
        assert lines_param.required is False
        assert lines_param.default == 100

        # Read tool should be READ_ONLY
        assert spec.permission == PermissionLevel.READ_ONLY

        # Test dangerous tool heuristic
        delete_tool = {"name": "delete_database", "inputSchema": {"type": "object"}}
        delete_spec = manager._adapt_mcp_tool_to_spec("test_server", mock_client, delete_tool)
        assert delete_spec.permission == PermissionLevel.DANGEROUS

        # Test write tool heuristic
        write_tool = {"name": "write_file", "inputSchema": {"type": "object"}}
        write_spec = manager._adapt_mcp_tool_to_spec("test_server", mock_client, write_tool)
        assert write_spec.permission == PermissionLevel.USER_CONFIRMATION

    def test_mcp_tool_execution_wrapper(self):
        registry = ToolRegistry()
        manager = MCPManager(registry)
        mock_client = MagicMock()
        mock_client.config = MCPServerConfig(name="mock", command="mock")
        mock_client.call_tool.return_value = ActionResult.ok("Mock file contents", intent="read_file")

        mcp_tool = {
            "name": "read_file",
            "description": "Read file",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }

        spec = manager._adapt_mcp_tool_to_spec("mock", mock_client, mcp_tool)
        registry.register(spec)

        result = registry.execute("mcp_mock_read_file", {"path": "test.txt"})
        assert result.success is True
        assert result.message == "Mock file contents"
        mock_client.call_tool.assert_called_once_with("read_file", {"path": "test.txt"})

    def test_mcp_client_call_tool_formatting(self):
        cfg = MCPServerConfig(name="test", command="test")
        client = MCPStdioClient(cfg)

        with patch.object(client, "send_request") as mock_send:
            mock_send.return_value = {
                "content": [{"type": "text", "text": "Execution successful output"}],
                "isError": False,
            }
            res = client.call_tool("test_tool", {"arg1": "val1"})
            assert res.success is True
            assert res.message == "Execution successful output"

            # Test error response
            mock_send.return_value = {
                "content": [{"type": "text", "text": "Permission denied"}],
                "isError": True,
            }
            err_res = client.call_tool("test_tool", {})
            assert err_res.success is False
            assert "Permission denied" in err_res.message

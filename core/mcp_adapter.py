"""
Model Context Protocol (MCP) Client Adapter.

Enables Flexiee to connect to any standard MCP server (over stdio JSON-RPC 2.0 or HTTP)
and seamlessly register its tools into Flexiee's ToolRegistry.

Inspired by the MCP architecture in Monaw Agent and Ari VoiceCommand.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.action_result import ActionResult
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec

logger = logging.getLogger("Flexie.MCP")


@dataclass
class MCPServerConfig:
    """Configuration for an external MCP server."""
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    enabled: bool = True
    timeout: float = 30.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "enabled": self.enabled,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MCPServerConfig:
        return cls(
            name=data["name"],
            command=data["command"],
            args=data.get("args", []),
            env=data.get("env", {}),
            cwd=data.get("cwd"),
            enabled=data.get("enabled", True),
            timeout=float(data.get("timeout", 30.0)),
        )


class MCPStdioClient:
    """Low-level JSON-RPC 2.0 client communicating over standard input/output."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.proc: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._pending_requests: Dict[int, threading.Event] = {}
        self._responses: Dict[int, dict] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self.server_info: Dict[str, Any] = {}
        self.capabilities: Dict[str, Any] = {}

    def start(self) -> bool:
        """Spawn the server process and initialize the MCP session."""
        if self._running and self.proc and self.proc.poll() is None:
            return True

        merged_env = os.environ.copy()
        merged_env.update(self.config.env)

        cmd = [self.config.command] + self.config.args
        try:
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=merged_env,
                cwd=self.config.cwd,
                startupinfo=startupinfo,
            )
            self._running = True

            self._reader_thread = threading.Thread(
                target=self._read_loop,
                name=f"mcp-reader-{self.config.name}",
                daemon=True,
            )
            self._reader_thread.start()

            # Initialize handshake
            init_res = self.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "Flexiee", "version": "2.0.0"},
                "capabilities": {"tools": {}},
            }, timeout=self.config.timeout)

            if not init_res:
                logger.error("MCP server %s failed initialize response", self.config.name)
                self.stop()
                return False

            self.server_info = init_res.get("serverInfo", {})
            self.capabilities = init_res.get("capabilities", {})

            # Notification: initialized
            self.send_notification("notifications/initialized", {})
            logger.info("MCP server %s initialized successfully (%s)", self.config.name, self.server_info)
            return True

        except Exception as e:
            logger.error("Failed to start MCP server %s: %s", self.config.name, e)
            self.stop()
            return False

    def _read_loop(self):
        """Continuously read line-delimited JSON-RPC messages from stdout."""
        while self._running and self.proc and self.proc.stdout:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                req_id = msg.get("id")
                if req_id is not None and req_id in self._pending_requests:
                    self._responses[req_id] = msg
                    self._pending_requests[req_id].set()
            except Exception:
                break
        self._running = False

    def send_request(self, method: str, params: Optional[dict] = None, timeout: float = 15.0) -> Optional[dict]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._running or not self.proc or not self.proc.stdin:
            return None

        with self._lock:
            self._req_id += 1
            req_id = self._req_id

        event = threading.Event()
        self._pending_requests[req_id] = event

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        try:
            line = json.dumps(payload) + "\n"
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
        except Exception as e:
            logger.error("Failed to write to MCP server %s: %s", self.config.name, e)
            self._pending_requests.pop(req_id, None)
            return None

        signaled = event.wait(timeout=timeout)
        self._pending_requests.pop(req_id, None)
        if not signaled:
            logger.warning("MCP request %s (id=%s) on %s timed out after %ss", method, req_id, self.config.name, timeout)
            return None

        resp = self._responses.pop(req_id, {})
        if "error" in resp:
            logger.error("MCP server %s returned error: %s", self.config.name, resp["error"])
            return None
        return resp.get("result")

    def send_notification(self, method: str, params: Optional[dict] = None):
        """Send a one-way notification."""
        if not self._running or not self.proc or not self.proc.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        try:
            line = json.dumps(payload) + "\n"
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
        except Exception as e:
            logger.warning("Failed to send notification to MCP %s: %s", self.config.name, e)

    def list_tools(self) -> List[dict]:
        """Query tools/list from server."""
        res = self.send_request("tools/list", {}, timeout=self.config.timeout)
        if not res or not isinstance(res, dict):
            return []
        return res.get("tools", [])

    def call_tool(self, name: str, arguments: dict, timeout: Optional[float] = None) -> ActionResult:
        """Invoke tools/call on the server."""
        t = timeout or self.config.timeout
        res = self.send_request("tools/call", {"name": name, "arguments": arguments}, timeout=t)
        if not res:
            return ActionResult.fail(message=f"MCP tool '{name}' call failed or timed out", intent=name)

        is_error = res.get("isError", False)
        content_items = res.get("content", [])
        text_parts = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
            else:
                text_parts.append(json.dumps(item))

        full_text = "\n".join(text_parts).strip()
        if is_error:
            return ActionResult.fail(message=full_text or "MCP tool execution returned an error", intent=name, data={"content": content_items})
        return ActionResult.ok(message=full_text, intent=name, data={"content": content_items})

    def stop(self):
        """Terminate server process gracefully."""
        self._running = False
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None


class MCPManager:
    """
    Coordinates external MCP servers, adapts their tools into ToolSpec,
    and registers them into Flexiee's ToolRegistry.
    """

    CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "mcp_servers.json")

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry
        self.clients: Dict[str, MCPStdioClient] = {}
        self.registered_tool_names: Dict[str, str] = {}  # tool_name -> server_name
        self.logger = logging.getLogger("Flexie.MCPManager")

    def add_server(self, config: MCPServerConfig) -> bool:
        """Add and connect to an MCP server, registering its tools."""
        if not config.enabled:
            return False

        client = MCPStdioClient(config)
        if not client.start():
            return False

        self.clients[config.name] = client
        self.refresh_tools_for_server(config.name)
        return True

    def remove_server(self, name: str):
        """Disconnect an MCP server and unregister its tools."""
        client = self.clients.pop(name, None)
        if client:
            client.stop()

        # Unregister tools
        if self.registry:
            to_remove = [t for t, s in self.registered_tool_names.items() if s == name]
            for t in to_remove:
                self.registry.unregister(t)
                self.registered_tool_names.pop(t, None)

    def refresh_tools_for_server(self, server_name: str) -> int:
        """Fetch tools from server and register with ToolRegistry."""
        client = self.clients.get(server_name)
        if not client or not self.registry:
            return 0

        raw_tools = client.list_tools()
        count = 0
        for tool_data in raw_tools:
            spec = self._adapt_mcp_tool_to_spec(server_name, client, tool_data)
            if spec:
                self.registry.register(spec)
                self.registered_tool_names[spec.name] = server_name
                count += 1

        self.logger.info("Registered %d tools from MCP server '%s'", count, server_name)
        return count

    def _adapt_mcp_tool_to_spec(self, server_name: str, client: MCPStdioClient, tool_data: dict) -> Optional[ToolSpec]:
        """Convert standard MCP tool definition to Flexiee ToolSpec."""
        raw_name = tool_data.get("name")
        if not raw_name:
            return None

        # Namespace to avoid colliding with native tools: mcp_{server}_{tool}
        tool_name = f"mcp_{server_name}_{raw_name}"
        description = tool_data.get("description", f"MCP Tool from {server_name}")
        input_schema = tool_data.get("inputSchema", {})

        properties = input_schema.get("properties", {})
        required_list = input_schema.get("required", [])

        params: List[ToolSchema] = []
        for p_name, p_info in properties.items():
            raw_type = p_info.get("type", "string")
            type_map = {
                "string": "str",
                "integer": "int",
                "number": "float",
                "boolean": "bool",
                "array": "list",
                "object": "dict",
            }
            param_type = type_map.get(raw_type, "str")
            params.append(ToolSchema(
                name=p_name,
                type=param_type,
                required=(p_name in required_list),
                default=p_info.get("default"),
                description=p_info.get("description", ""),
                enum=p_info.get("enum"),
            ))

        # Assign permission level heuristically
        lower_name = raw_name.lower()
        if any(w in lower_name for w in ["delete", "remove", "drop", "destroy", "terminate"]):
            permission = PermissionLevel.DANGEROUS
        elif any(w in lower_name for w in ["write", "create", "update", "patch", "modify", "send", "post"]):
            permission = PermissionLevel.USER_CONFIRMATION
        else:
            permission = PermissionLevel.READ_ONLY

        def execute_wrapper(**kwargs) -> ActionResult:
            return client.call_tool(raw_name, kwargs)

        return ToolSpec(
            name=tool_name,
            description=f"[{server_name}] {description}",
            params=params,
            permission=permission,
            execute_fn=execute_wrapper,
            timeout=client.config.timeout,
            tags=["mcp", server_name],
        )

    def load_configs(self) -> List[MCPServerConfig]:
        """Load configured MCP servers from json."""
        if not os.path.exists(self.CONFIG_FILE):
            return []
        try:
            with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            configs = []
            servers = data.get("mcpServers", data)
            if isinstance(servers, dict):
                for name, s_data in servers.items():
                    s_data["name"] = name
                    configs.append(MCPServerConfig.from_dict(s_data))
            return configs
        except Exception as e:
            self.logger.warning("Could not read MCP config file %s: %s", self.CONFIG_FILE, e)
            return []

    def start_configured_servers(self):
        """Start all enabled servers defined in config."""
        for cfg in self.load_configs():
            try:
                self.add_server(cfg)
            except Exception as e:
                self.logger.error("Failed to start MCP server %s: %s", cfg.name, e)

    def shutdown(self):
        """Stop all running MCP servers."""
        for name, client in list(self.clients.items()):
            try:
                client.stop()
            except Exception:
                pass
        self.clients.clear()

"""
Tool Abstraction Layer — centralizes all tool registration, validation,
permission checking, and execution for the agent system.

Each tool has:
  - unique name
  - description
  - input schema (dict of param_name -> {"type": ..., "required": ..., "description": ...})
  - permission level (from PermissionLevel enum)
  - execute function (callable)
  - result format (str: " ActionResult", "text", "json", "file")
  - timeout (seconds)
  - verification function (optional callable)
  - error handling strategy (str: "retry", "fallback", "escalate", "abort")

The LLM never executes arbitrary code. It requests a registered tool by name.
"""
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

from core.action_result import ActionResult


class PermissionLevel(Enum):
    """Permission levels for tool execution, ordered from least to most restrictive."""
    READ_ONLY = 1        # search, read, inspect — no side effects
    SAFE_ACTION = 2      # open app, change volume, search web — reversible
    USER_CONFIRMATION = 3  # move files, send email, modify code — ask first
    SENSITIVE = 4        # terminate process, system config — warn + confirm
    DANGEROUS = 5        # delete permanently, destructive shell — block unless overridden


# Maps permission level names to enum for LLM-friendly usage
PERMISSION_NAMES = {level.name: level for level in PermissionLevel}
PERMISSION_LEVELS = {level.value: level.name for level in PermissionLevel}


@dataclass
class ToolSchema:
    """Describes a single parameter of a tool."""
    name: str
    type: str  # "str", "int", "float", "bool", "list", "dict"
    required: bool = True
    default: Any = None
    description: str = ""
    enum: Optional[List[Any]] = None  # allowed values

    def to_dict(self) -> dict:
        d = {"type": self.type, "required": self.required, "description": self.description}
        if self.default is not None:
            d["default"] = self.default
        if self.enum is not None:
            d["enum"] = self.enum
        return d


@dataclass
class ToolSpec:
    """Complete specification for a registered tool."""
    name: str
    description: str
    params: List[ToolSchema]
    permission: PermissionLevel
    execute_fn: Callable[..., ActionResult]
    result_format: str = "ActionResult"  # "ActionResult", "text", "json", "file"
    timeout: float = 10.0
    verify_fn: Optional[Callable[..., bool]] = None
    error_strategy: str = "abort"  # "retry", "fallback", "escalate", "abort"
    max_retries: int = 2
    tags: List[str] = field(default_factory=list)  # for grouping: "browser", "file", "system"
    enabled: bool = True

    def input_schema_dict(self) -> dict:
        """Returns JSON-schema-like dict for LLM consumption."""
        return {p.name: p.to_dict() for p in self.params}

    def validate_args(self, args: dict) -> tuple[bool, str]:
        """Validates provided args against the schema. Returns (ok, error_msg)."""
        for param in self.params:
            if param.required and param.name not in args:
                # Check default
                if param.default is not None:
                    continue
                return False, f"Missing required parameter: {param.name}"
            if param.name in args:
                val = args[param.name]
                # Type checking
                type_map = {"str": str, "int": int, "float": (int, float), "bool": bool, "list": list, "dict": dict}
                expected = type_map.get(param.type)
                if expected and not isinstance(val, expected):
                    return False, f"Parameter '{param.name}' expected {param.type}, got {type(val).__name__}"
                # Enum checking
                if param.enum and val not in param.enum:
                    return False, f"Parameter '{param.name}' must be one of {param.enum}, got {val!r}"
        # Check for unknown params
        known = {p.name for p in self.params}
        unknown = set(args.keys()) - known
        if unknown:
            return False, f"Unknown parameters: {unknown}"
        return True, ""


class ToolRegistry:
    """
    Central registry for all tools. Singleton-like (use the module-level instance).
    
    Tools are registered at startup. The LLM or agent planner queries the registry
    to find available tools, and calls execute() to run them.
    """

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self.logger = logging.getLogger("Flexie.ToolRegistry")

    def register(self, tool: ToolSpec):
        """Register a tool. Overwrites if name already exists."""
        self._tools[tool.name] = tool
        self.logger.debug(f"[TOOL] Registered: {tool.name} (permission={tool.permission.name})")

    def unregister(self, name: str):
        """Remove a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[ToolSpec]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self, tag: Optional[str] = None, enabled_only: bool = True) -> List[ToolSpec]:
        """List all tools, optionally filtered by tag."""
        tools = list(self._tools.values())
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        if tag:
            tools = [t for t in tools if tag in t.tags]
        return tools

    def list_tool_names(self, tag: Optional[str] = None) -> List[str]:
        """Returns list of tool names."""
        return [t.name for t in self.list_tools(tag)]

    def get_tools_for_llm(self, tag: Optional[str] = None) -> List[dict]:
        """
        Returns tool definitions optimized for LLM function-calling.
        Each entry: {"name": ..., "description": ..., "parameters": {...}, "permission": ...}
        """
        tools = self.list_tools(tag)
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema_dict(),
                "permission": t.permission.name,
                "timeout": t.timeout,
            }
            for t in tools
        ]

    def validate_args(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Validate arguments for a specific tool."""
        tool = self.get(tool_name)
        if not tool:
            return False, f"Unknown tool: {tool_name}"
        if not tool.enabled:
            return False, f"Tool is disabled: {tool_name}"
        return tool.validate_args(args)

    def check_permission(self, tool_name: str, current_level: PermissionLevel) -> bool:
        """
        Checks if the current permission level allows executing the tool.
        Returns True if allowed.
        """
        tool = self.get(tool_name)
        if not tool:
            return False
        return tool.permission.value <= current_level.value

    def execute(self, tool_name: str, args: dict, timeout: Optional[float] = None) -> ActionResult:
        """
        Execute a tool with validated arguments.
        
        This is the ONLY way tools should be invoked by the agent.
        Returns ActionResult with success/failure details.
        """
        tool = self.get(tool_name)
        if not tool:
            return ActionResult.fail(message=f"Unknown tool: {tool_name}", intent=tool_name)
        if not tool.enabled:
            return ActionResult.fail(message=f"Tool disabled: {tool_name}", intent=tool_name)

        # Validate args
        ok, err = tool.validate_args(args)
        if not ok:
            return ActionResult.fail(message=f"Invalid args: {err}", intent=tool_name, data={"error": err})

        # Execute
        effective_timeout = timeout or tool.timeout
        try:
            result = tool.execute_fn(**args)
            # Ensure result is ActionResult
            if not isinstance(result, ActionResult):
                result = ActionResult.ok(message=str(result), intent=tool_name, data={"raw": result})
            result.intent = tool_name
            return result
        except TimeoutError:
            return ActionResult.fail(
                message=f"Tool '{tool_name}' timed out after {effective_timeout}s",
                intent=tool_name,
                data={"timeout": effective_timeout}
            )
        except Exception as e:
            return ActionResult.fail(
                message=f"Tool '{tool_name}' error: {e}",
                intent=tool_name,
                data={"error": str(e), "error_type": type(e).__name__}
            )

    def verify(self, tool_name: str, result: ActionResult) -> bool:
        """Run the tool's verification function if it has one."""
        tool = self.get(tool_name)
        if not tool or not tool.verify_fn:
            return result.success  # default: trust success flag
        try:
            return tool.verify_fn(result)
        except Exception:
            return False

    def to_summary(self) -> str:
        """Human-readable summary of all registered tools."""
        tools = self.list_tools()
        lines = [f"Registered Tools ({len(tools)}):"]
        for t in sorted(tools, key=lambda x: x.permission.value):
            lines.append(f"  [{t.permission.name:18s}] {t.name}: {t.description}")
        return "\n".join(lines)


# Module-level singleton
registry = ToolRegistry()

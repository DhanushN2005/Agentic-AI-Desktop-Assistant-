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
import contextvars
import logging
import math
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.action_result import ActionResult
from core.capabilities import CapabilityPolicy

# Tools carrying these tags return content authored by third parties (web pages, email,
# MCP servers). That content is untrusted DATA: it may contain injected instructions.
UNTRUSTED_SOURCE_TAGS = frozenset({"web", "extract", "email", "mcp"})


# Tools carrying these tags touch thread-affine resources (Playwright pages, COM, the desktop
# session). They must run on the calling thread, so their timeout is reported, not interrupted.
THREAD_AFFINE_TAGS = frozenset({"browser", "automation", "desktop", "vision", "clipboard", "app"})


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
    enum: list[Any] | None = None  # allowed values
    minimum: float | None = None  # inclusive numeric bound (int/float)
    maximum: float | None = None  # inclusive numeric bound (int/float)
    max_length: int | None = None  # str / list length cap

    def to_dict(self) -> dict:
        d = {"type": self.type, "required": self.required, "description": self.description}
        if self.default is not None:
            d["default"] = self.default
        if self.enum is not None:
            d["enum"] = self.enum
        if self.minimum is not None:
            d["minimum"] = self.minimum
        if self.maximum is not None:
            d["maximum"] = self.maximum
        if self.max_length is not None:
            d["max_length"] = self.max_length
        return d


@dataclass
class ToolSpec:
    """Complete specification for a registered tool."""
    name: str
    description: str
    params: list[ToolSchema]
    permission: PermissionLevel
    execute_fn: Callable[..., ActionResult]
    result_format: str = "ActionResult"  # "ActionResult", "text", "json", "file"
    timeout: float = 10.0
    verify_fn: Callable[..., bool] | None = None
    error_strategy: str = "abort"  # "retry", "fallback", "escalate", "abort"
    max_retries: int = 2
    tags: list[str] = field(default_factory=list)  # for grouping: "browser", "file", "system"
    enabled: bool = True
    capabilities: list[str] = field(default_factory=list)
    # True: running it again leaves the same state (safe to retry after an inconclusive check).
    # None: unknown -> treated as NOT repeatable (only idempotent=True is ever retried).
    idempotent: bool | None = None

    def input_schema_dict(self) -> dict:
        """Returns JSON-schema-like dict for LLM consumption."""
        return {p.name: p.to_dict() for p in self.params}

    def effective_capabilities(self) -> list[str]:
        """Declared capabilities, or a conservative set inferred from tags/permission."""
        if self.capabilities:
            return list(self.capabilities)
        caps: set[str] = set()
        tags = set(self.tags)
        if tags & {"terminal", "shell"}:
            caps.add("shell:execute")
        if tags & {"file", "filesystem", "code"}:
            caps.add("filesystem:read")
        if self.permission.value >= PermissionLevel.USER_CONFIRMATION.value:
            caps.add("filesystem:write")
        if tags & {"browser", "search", "network"}:
            caps.add("network:fetch")
        return sorted(caps)

    def validate_args(self, args: dict) -> tuple[bool, str]:
        """Validates provided args against the schema. Returns (ok, error_msg)."""
        ok, err, _ = self.normalize_args(args)
        return ok, err

    def normalize_args(self, args: dict) -> tuple[bool, str, dict]:
        """Validate ``args`` and return them with declared defaults applied.

        Rejects bool for int/float, NaN/inf, out-of-range numbers (``minimum``/``maximum``),
        over-long str/list (``max_length``), enum violations and unknown parameters. The input
        dict is only copied when a default has to be filled in.
        """
        out = args
        seen = 0
        for param in self.params:
            name = param.name
            if name not in args:
                if param.default is not None:
                    if out is args:
                        out = dict(args)
                    out[name] = param.default
                    continue
                if param.required:
                    return False, f"Missing required parameter: {name}", args
                continue
            seen += 1
            val = args[name]
            expected = _TYPE_MAP.get(param.type)
            if expected is not None:
                numeric = param.type in ("int", "float")
                if not isinstance(val, expected) or (numeric and isinstance(val, bool)):
                    return False, f"Parameter '{name}' expected {param.type}, got {type(val).__name__}", args
                if numeric:
                    if isinstance(val, float) and not math.isfinite(val):
                        return False, f"Parameter '{name}' must be a finite number, got {val!r}", args
                    if param.minimum is not None and val < param.minimum:
                        return False, f"Parameter '{name}' must be >= {param.minimum}, got {val!r}", args
                    if param.maximum is not None and val > param.maximum:
                        return False, f"Parameter '{name}' must be <= {param.maximum}, got {val!r}", args
                elif param.max_length is not None and param.type in ("str", "list") and len(val) > param.max_length:
                    return False, f"Parameter '{name}' is too long ({len(val)} > {param.max_length})", args
            if param.enum and val not in param.enum:
                return False, f"Parameter '{name}' must be one of {param.enum}, got {val!r}", args
        if seen != len(args):
            unknown = set(args.keys()) - {p.name for p in self.params}
            return False, f"Unknown parameters: {unknown}", args
        return True, "", out


_TYPE_MAP = {"str": str, "int": int, "float": (int, float), "bool": bool, "list": list, "dict": dict}


class _WorkerPool:
    """Tiny pool of DAEMON worker threads (ThreadPoolExecutor workers are non-daemon and are
    joined at interpreter exit, so one hung tool would block shutdown). A call that overruns
    its timeout keeps its worker busy; the pool simply spawns another for later calls.
    """

    IDLE_EXIT_S = 30.0

    def __init__(self) -> None:
        self._q: queue.SimpleQueue = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._idle = 0

    def submit(self, fn: Callable[[], None]) -> None:
        with self._lock:
            if self._idle > 0:
                self._idle -= 1
                self._q.put(fn)
                return
        threading.Thread(target=self._worker, args=(fn,), name="tool-worker", daemon=True).start()

    def _worker(self, job: Callable[[], None]) -> None:
        while True:
            try:
                job()
            except BaseException as exc:  # jobs capture their own errors; never kill the worker
                logging.debug("[TOOL] worker job raised: %s", exc)
            with self._lock:
                self._idle += 1
            while True:
                try:
                    job = self._q.get(timeout=self.IDLE_EXIT_S)
                    break
                except queue.Empty:
                    with self._lock:
                        if self._q.empty():
                            self._idle -= 1
                            return


_POOL = _WorkerPool()


class _InFlightError(Exception):
    """A previous timed-out call to the same side-effecting tool is still running."""


class ToolRegistry:
    """
    Central registry for all tools. Singleton-like (use the module-level instance).

    Tools are registered at startup. The LLM or agent planner queries the registry
    to find available tools, and calls execute() to run them.
    """

    def __init__(self, policy: CapabilityPolicy | None = None):
        self._tools: dict[str, ToolSpec] = {}
        self.logger = logging.getLogger("Flexie.ToolRegistry")
        self.policy = policy or CapabilityPolicy()
        # Optional PermissionSystem. When set, execute() fails CLOSED for any tool
        # whose required level exceeds the current level — callers cannot skip it.
        self.permission_gate = None
        # (tool, args-hash) -> box of a timed-out, non-idempotent call that may still be running
        self._stuck: dict[tuple[str, int], dict] = {}

    def register(self, tool: ToolSpec):
        """Register a tool. Overwrites if name already exists."""
        ok, err = self.policy.validate_tool(tool.capabilities, tool.effective_capabilities())
        if not ok:
            self.logger.warning("[TOOL] %s declares invalid capabilities: %s", tool.name, err)
        self._tools[tool.name] = tool
        self.logger.debug(f"[TOOL] Registered: {tool.name} (permission={tool.permission.name})")

    def unregister(self, name: str):
        """Remove a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self, tag: str | None = None, enabled_only: bool = True) -> list[ToolSpec]:
        """List all tools, optionally filtered by tag."""
        tools = list(self._tools.values())
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        if tag:
            tools = [t for t in tools if tag in t.tags]
        return tools

    def list_tool_names(self, tag: str | None = None) -> list[str]:
        """Returns list of tool names."""
        return [t.name for t in self.list_tools(tag)]

    def get_tools_for_llm(self, tag: str | None = None) -> list[dict]:
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

    def execute(self, tool_name: str, args: dict, timeout: float | None = None) -> ActionResult:
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

        if self.permission_gate is not None:
            allowed, reason, required = self.permission_gate.check_permission(tool)
            if not allowed:
                return ActionResult.fail(
                    message=f"Permission denied: {reason}",
                    intent=tool_name,
                    data={"error": reason, "required_level": required.name if required else None,
                          "permission_denied": True},
                )

        cap_ok, cap_err = self.policy.validate_tool(tool.capabilities, tool.effective_capabilities())
        if not cap_ok:
            return ActionResult.fail(
                message=f"Capability denied: {cap_err}",
                intent=tool_name,
                data={"error": cap_err},
            )

        # Validate args (and fill in declared defaults)
        ok, err, args = tool.normalize_args(args)
        if not ok:
            return ActionResult.fail(message=f"Invalid args: {err}", intent=tool_name, data={"error": err})

        # Content from third parties is untrusted whether the call succeeded, failed or timed
        # out: an injected instruction can just as well sit in an error message.
        if self.permission_gate is not None and any(t in UNTRUSTED_SOURCE_TAGS for t in tool.tags):
            self.permission_gate.mark_untrusted(tool_name)

        # Execute
        effective_timeout = self._effective_timeout(tool, args, timeout)
        try:
            result = self._invoke(tool, args, effective_timeout)
            # Ensure result is ActionResult
            if not isinstance(result, ActionResult):
                result = ActionResult.ok(message=str(result), intent=tool_name, data={"raw": result})
            result.intent = tool_name
            return result
        except _InFlightError as _e:
            return ActionResult.fail(
                message=f"Tool '{tool_name}' is still running from a previous timed-out call; "
                        "not starting it twice (outcome unknown)",
                intent=tool_name,
                data={"in_flight": True, "outcome_unknown": True},
            )
        except TimeoutError as _e:
            logging.debug("[core/tool_registry.py:207] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return ActionResult.fail(
                message=f"Tool '{tool_name}' timed out after {effective_timeout:.0f}s (outcome unknown)",
                intent=tool_name,
                data={"timeout": effective_timeout, "outcome_unknown": True},
            )
        except Exception as e:
            logging.debug("[core/tool_registry.py:213] Swallowed exception: %s: %s", type(e).__name__, e)
            return ActionResult.fail(
                message=f"Tool '{tool_name}' error: {e}",
                intent=tool_name,
                data={"error": str(e), "error_type": type(e).__name__}
            )

    @staticmethod
    def _effective_timeout(tool: "ToolSpec", args: dict, requested: float | None) -> float:
        """Never shorter than what the tool itself declares it needs.

        A plan step's default timeout (15 s) must not cut a 65 s test run, and a tool that takes
        its own ``timeout`` argument (terminal.run, python.exec) gets that plus a little slack.
        """
        candidates = [tool.timeout or 0, requested or 0]
        own = args.get("timeout") if isinstance(args, dict) else None
        if isinstance(own, (int, float)) and not isinstance(own, bool) and own > 0:
            candidates.append(own + 5)
        value = max(candidates)
        return value if value > 0 else 30.0

    def _invoke(self, tool: "ToolSpec", args: dict, timeout: float) -> Any:
        """Run the tool, enforcing ``timeout`` where that is safe.

        Thread-affine tools run inline; if they overrun, the result is kept (the action did
        happen) but flagged ``slow``. Everything else runs in a worker thread and a call that
        overruns is reported as a timeout instead of blocking the agent. Python cannot kill a
        thread, so a timed-out call may still finish in the background; callers must treat a
        timeout as "outcome unknown", not "did not happen".
        """
        if any(t in THREAD_AFFINE_TAGS for t in tool.tags):
            started = time.monotonic()
            result = tool.execute_fn(**args)
            elapsed = time.monotonic() - started
            if elapsed > timeout:
                logging.warning("[TOOL] %s took %.1fs (limit %.0fs); thread-affine tool, not interrupted",
                                tool.name, elapsed, timeout)
                if isinstance(result, ActionResult):
                    result.data = {**(result.data or {}), "slow_seconds": round(elapsed, 2)}
            return result

        if self._stuck:
            key = self._call_key(tool.name, args)
            stuck = self._stuck.get(key)
            if stuck is not None:
                if not stuck.get("done"):
                    raise _InFlightError(tool.name)
                self._stuck.pop(key, None)

        box: dict[str, Any] = {}
        done = threading.Lock()
        done.acquire()
        ctx = contextvars.copy_context()  # keep per-command usage attribution inside the worker
        fn = tool.execute_fn

        def _run() -> None:
            try:
                box["result"] = ctx.run(fn, **args)
            except BaseException as exc:  # re-raised on the caller's thread below
                box["error"] = exc
            finally:
                box["done"] = True
                done.release()

        _POOL.submit(_run)
        if not done.acquire(timeout=timeout):
            if not self._repeatable(tool):
                # A retry must not start the same side effect while this one may still be running.
                if len(self._stuck) > 256:
                    for k in [k for k, b in self._stuck.items() if b.get("done")]:
                        self._stuck.pop(k, None)
                self._stuck[self._call_key(tool.name, args)] = box
            raise TimeoutError(f"no result after {timeout:.0f}s; it may still be running in the background")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    @staticmethod
    def _repeatable(tool: "ToolSpec") -> bool:
        return tool.idempotent is True

    @staticmethod
    def _call_key(name: str, args: dict) -> tuple[str, int]:
        try:
            return name, hash(repr(sorted(args.items())))
        except Exception:
            return name, 0

    def verify(self, tool_name: str, result: ActionResult) -> bool:
        """Run the tool's verification function if it has one."""
        tool = self.get(tool_name)
        if not tool or not tool.verify_fn:
            return result.success  # default: trust success flag
        try:
            return tool.verify_fn(result)
        except Exception as _e:
            logging.debug("[core/tool_registry.py:227] Swallowed exception: %s: %s", type(_e).__name__, _e)
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

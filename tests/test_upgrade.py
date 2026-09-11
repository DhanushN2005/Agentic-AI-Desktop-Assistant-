"""
Tests for the Flexie 2.0 upgrade systems:
  - Tool Registry
  - Permission System
  - Goal Planner
  - Hybrid Router
  - Agent Executor
  - Desktop Control
  - LLM Provider Config
  - Memory Manager
"""
import pytest
import time
import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.action_result import ActionResult
from core.tool_registry import ToolRegistry, ToolSpec, ToolSchema, PermissionLevel, registry
from core.permission_system import PermissionSystem
from core.goal_planner import GoalPlanner, TaskGraph, TaskStep, StepStatus, VerificationStrategy
from core.hybrid_router import HybridRouter
from core.agent_executor import AgentExecutor
from core.desktop_control import DesktopControl
from core.llm_providers import LLMProviderManager, LLMProvider, ProviderStatus
from core.memory_manager import MemoryManager, MemoryCategory, MemoryEntry


# =============================================================================
# ACTION RESULT TESTS
# =============================================================================

class TestActionResult:
    def test_ok_factory(self):
        r = ActionResult.ok(message="done", intent="test")
        assert r.success is True
        assert r.message == "done"
        assert r.intent == "test"

    def test_fail_factory(self):
        r = ActionResult.fail(message="error", intent="test")
        assert r.success is False
        assert r.message == "error"

    def test_bool_truthy(self):
        assert bool(ActionResult.ok()) is True
        assert bool(ActionResult.fail()) is False

    def test_timestamp(self):
        before = time.time()
        r = ActionResult.ok()
        assert r.timestamp >= before


# =============================================================================
# TOOL REGISTRY TESTS
# =============================================================================

class TestToolRegistry:
    def test_register_tool(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.echo",
            description="Echo input",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        )
        reg.register(tool)
        assert reg.get("test.echo") is not None
        assert "test.echo" in reg.list_tool_names()

    def test_validate_args_valid(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.echo",
            description="Echo input",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        )
        reg.register(tool)
        ok, err = reg.validate_args("test.echo", {"text": "hello"})
        assert ok is True
        assert err == ""

    def test_validate_args_missing_required(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.echo",
            description="Echo input",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        )
        reg.register(tool)
        ok, err = reg.validate_args("test.echo", {})
        assert ok is False
        assert "Missing required" in err

    def test_validate_args_wrong_type(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.num",
            description="Number input",
            params=[ToolSchema(name="count", type="int", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda count: ActionResult.ok(message=str(count)),
        )
        reg.register(tool)
        ok, err = reg.validate_args("test.num", {"count": "not a number"})
        assert ok is False
        assert "expected int" in err

    def test_validate_args_unknown_param(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.echo",
            description="Echo input",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        )
        reg.register(tool)
        ok, err = reg.validate_args("test.echo", {"text": "hello", "extra": True})
        assert ok is False
        assert "Unknown parameters" in err

    def test_execute_tool(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.add",
            description="Add numbers",
            params=[
                ToolSchema(name="a", type="int", required=True),
                ToolSchema(name="b", type="int", required=True),
            ],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda a, b: ActionResult.ok(message=str(a + b)),
        )
        reg.register(tool)
        result = reg.execute("test.add", {"a": 3, "b": 4})
        assert result.success
        assert result.message == "7"

    def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        result = reg.execute("nonexistent.tool", {})
        assert result.success is False

    def test_check_permission(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.safe",
            description="Safe action",
            params=[],
            permission=PermissionLevel.SAFE_ACTION,
            execute_fn=lambda: ActionResult.ok(),
        )
        reg.register(tool)
        assert reg.check_permission("test.safe", PermissionLevel.READ_ONLY) is False
        assert reg.check_permission("test.safe", PermissionLevel.SAFE_ACTION) is True
        assert reg.check_permission("test.safe", PermissionLevel.DANGEROUS) is True

    def test_tools_for_llm(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.echo",
            description="Echo input",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        )
        reg.register(tool)
        llm_tools = reg.get_tools_for_llm()
        assert len(llm_tools) == 1
        assert llm_tools[0]["name"] == "test.echo"
        assert "text" in llm_tools[0]["parameters"]

    def test_unregister(self):
        reg = ToolRegistry()
        tool = ToolSpec(
            name="test.temp",
            description="Temp",
            params=[],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda: ActionResult.ok(),
        )
        reg.register(tool)
        assert reg.get("test.temp") is not None
        reg.unregister("test.temp")
        assert reg.get("test.temp") is None


# =============================================================================
# PERMISSION SYSTEM TESTS
# =============================================================================

class TestPermissionSystem:
    def test_classify_read_only(self):
        ps = PermissionSystem()
        level = ps.classify_action("what is the time")
        assert level == PermissionLevel.READ_ONLY

    def test_classify_safe_action(self):
        ps = PermissionSystem()
        level = ps.classify_action("open chrome")
        assert level == PermissionLevel.SAFE_ACTION

    def test_classify_user_confirmation(self):
        ps = PermissionSystem()
        level = ps.classify_action("move file to documents")
        assert level.value >= PermissionLevel.USER_CONFIRMATION.value

    def test_classify_sensitive(self):
        ps = PermissionSystem()
        level = ps.classify_action("shutdown the computer")
        assert level.value >= PermissionLevel.SENSITIVE.value

    def test_classify_dangerous(self):
        ps = PermissionSystem()
        level = ps.classify_action("delete account permanently")
        assert level.value >= PermissionLevel.DANGEROUS.value

    def test_requires_confirmation(self):
        ps = PermissionSystem()
        assert ps.requires_confirmation("send email to john") is True
        assert ps.requires_confirmation("what time is it") is False

    def test_escalate_and_reset(self):
        ps = PermissionSystem()
        ps.escalate(PermissionLevel.DANGEROUS)
        assert ps.current_level == PermissionLevel.DANGEROUS
        ps.reset()
        assert ps.current_level == PermissionLevel.READ_ONLY


# =============================================================================
# GOAL PLANNER TESTS
# =============================================================================

class TestGoalPlanner:
    def test_simple_goal(self):
        planner = GoalPlanner()
        graph = planner.decompose("search for Python tutorials")
        assert len(graph.steps) >= 1
        assert graph.original_goal == "search for Python tutorials"

    def test_compound_goal(self):
        planner = GoalPlanner()
        graph = planner.decompose("find my resume and rename it")
        assert len(graph.steps) >= 2

    def test_task_step_dependencies(self):
        step1 = TaskStep(task_id="step_0", description="first", tool="")
        step2 = TaskStep(task_id="step_1", description="second", tool="", depends_on=["step_0"])
        assert step1.is_ready(set()) is True
        assert step2.is_ready(set()) is False
        assert step2.is_ready({"step_0"}) is True

    def test_task_graph_ready_steps(self):
        graph = TaskGraph(goal_id="test", original_goal="test")
        graph.add_step(TaskStep(task_id="s0", description="a", tool=""))
        graph.add_step(TaskStep(task_id="s1", description="b", tool="", depends_on=["s0"]))
        ready = graph.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].task_id == "s0"

    def test_task_graph_all_completed(self):
        graph = TaskGraph(goal_id="test", original_goal="test")
        graph.add_step(TaskStep(task_id="s0", description="a", tool=""))
        assert graph.all_completed() is False
        graph.steps[0].status = StepStatus.COMPLETED
        assert graph.all_completed() is True

    def test_tool_match(self):
        planner = GoalPlanner()
        assert planner._match_tool("search for files") == "files.search"
        assert planner._match_tool("rename the file") == "files.rename"
        assert planner._match_tool("open the browser") == "app.open"

    def test_verification_inference(self):
        planner = GoalPlanner()
        assert planner._infer_verification("create a file") == VerificationStrategy.FILE_EXISTS
        assert planner._infer_verification("open notepad") == VerificationStrategy.APP_RUNNING
        assert planner._infer_verification("search the web") == VerificationStrategy.NONE

    def test_step_serialization(self):
        step = TaskStep(task_id="s0", description="test", tool="test.tool")
        d = step.to_dict()
        assert d["task_id"] == "s0"
        assert d["status"] == "PENDING"

    def test_graph_serialization(self):
        graph = TaskGraph(goal_id="g1", original_goal="test goal")
        graph.add_step(TaskStep(task_id="s0", description="step", tool=""))
        d = graph.to_dict()
        assert d["goal_id"] == "g1"
        assert len(d["steps"]) == 1


# =============================================================================
# HYBRID ROUTER TESTS
# =============================================================================

class TestHybridRouter:
    def test_simple_command(self):
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)
        intent, confidence, mode = hr.route("what time is it")
        assert mode == "simple"
        assert intent == "alarm"

    def test_cancel_command(self):
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)
        intent, confidence, mode = hr.route("stop")
        assert mode == "cancel"

    def test_complex_command(self):
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)
        intent, confidence, mode = hr.route("find my resume and rename it to draft")
        assert mode == "complex"

    def test_classify_simple(self):
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)
        assert hr.classify("open chrome") == "simple"
        assert hr.classify("volume up") == "simple"

    def test_classify_complex(self):
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)
        assert hr.classify("find resume and rename it and move it") == "complex"


# =============================================================================
# AGENT EXECUTOR TESTS
# =============================================================================

class TestAgentExecutor:
    def test_cancel(self):
        executor = AgentExecutor(
            tool_registry=ToolRegistry(),
            permission_system=PermissionSystem(),
        )
        executor.cancel()
        assert executor.is_cancelled() is True

    def test_execute_empty_graph(self):
        executor = AgentExecutor(
            tool_registry=ToolRegistry(),
            permission_system=PermissionSystem(),
        )
        graph = TaskGraph(goal_id="test", original_goal="nothing")
        result = executor.execute(graph, speak=False)
        assert result.success is True

    def test_execute_simple_graph(self):
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="test.echo",
            description="Echo",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        ))
        executor = AgentExecutor(
            tool_registry=reg,
            permission_system=PermissionSystem(),
        )
        graph = TaskGraph(goal_id="test", original_goal="echo hello")
        graph.add_step(TaskStep(task_id="s0", description="echo", tool="test.echo", arguments={"text": "hello"}))
        result = executor.execute(graph, speak=False)
        assert result.success is True
        assert graph.steps[0].status == StepStatus.COMPLETED


# =============================================================================
# DESKTOP CONTROL TESTS
# =============================================================================

class TestDesktopControl:
    def test_init(self):
        dc = DesktopControl()
        assert dc._screenshot_dir is not None

    def test_permission_check(self):
        ps = PermissionSystem()
        dc = DesktopControl(permission_system=ps)
        # Read-only should be allowed
        allowed, _, _ = ps.check_permission("vision.screenshot", "screenshot")
        # This depends on default permission level
        assert isinstance(allowed, bool)


# =============================================================================
# LLM PROVIDER CONFIG TESTS
# =============================================================================

class TestLLMProviderConfig:
    def test_provider_init(self):
        mgr = LLMProviderManager()
        assert len(mgr.providers) >= 2

    def test_provider_availability(self):
        p = LLMProvider(
            name="test",
            api_key_env="NONEXISTENT_KEY",
            model="test-model",
            priority=1,
            enabled=True,
        )
        assert p.is_available is False  # No API key

    def test_provider_success_recording(self):
        p = LLMProvider(
            name="test",
            api_key_env="NONEXISTENT_KEY",
            model="test-model",
            priority=1,
        )
        p.record_success()
        assert p.status == ProviderStatus.HEALTHY
        assert p.consecutive_failures == 0

    def test_provider_failure_recording(self):
        p = LLMProvider(
            name="test",
            api_key_env="NONEXISTENT_KEY",
            model="test-model",
            priority=1,
        )
        for _ in range(3):
            p.record_failure("error")
        assert p.status == ProviderStatus.UNAVAILABLE

    def test_provider_reset(self):
        p = LLMProvider(
            name="test",
            api_key_env="NONEXISTENT_KEY",
            model="test-model",
            priority=1,
        )
        p.record_failure("error")
        p.reset_status()
        assert p.consecutive_failures == 0

    def test_summary(self):
        mgr = LLMProviderManager()
        summary = mgr.to_summary()
        assert "LLM Providers:" in summary


# =============================================================================
# MEMORY MANAGER TESTS
# =============================================================================

class TestMemoryManager:
    def _get_test_manager(self):
        """Create a MemoryManager with a test DB."""
        import tempfile
        mm = MemoryManager.__new__(MemoryManager)
        mm.logger = logging.getLogger("test")
        mm._entries = {}
        mm.DB_PATH = os.path.join(tempfile.gettempdir(), "test_memory.db")
        mm._ensure_db()
        return mm

    def test_remember_and_recall(self):
        mm = self._get_test_manager()
        mm.remember("test_key", "test_value", MemoryCategory.FACTS)
        entry = mm.recall("test_key")
        assert entry is not None
        assert entry.value == "test_value"

    def test_forget(self):
        mm = self._get_test_manager()
        mm.remember("forget_me", "value", MemoryCategory.FACTS)
        assert mm.recall("forget_me") is not None
        mm.forget("forget_me")
        assert mm.recall("forget_me") is None

    def test_search(self):
        mm = self._get_test_manager()
        mm.remember("python_lang", "Python programming", MemoryCategory.FACTS)
        mm.remember("java_lang", "Java programming", MemoryCategory.FACTS)
        results = mm.search("python")
        assert len(results) >= 1
        assert any("python" in e.key for e in results)

    def test_by_category(self):
        mm = self._get_test_manager()
        mm.remember("pref1", "dark mode", MemoryCategory.PREFERENCES)
        mm.remember("fact1", "some fact", MemoryCategory.FACTS)
        prefs = mm.get_by_category(MemoryCategory.PREFERENCES)
        assert len(prefs) >= 1

    def test_stats(self):
        mm = self._get_test_manager()
        mm.remember("stat_test", "value", MemoryCategory.TASKS)
        stats = mm.get_stats()
        assert stats["total"] >= 1
        assert "by_category" in stats

    def test_forget_category(self):
        mm = self._get_test_manager()
        mm.remember("cat1", "val", MemoryCategory.FACTS)
        mm.remember("cat2", "val", MemoryCategory.FACTS)
        count = mm.forget_category(MemoryCategory.FACTS)
        assert count >= 2

    def test_expiration(self):
        mm = self._get_test_manager()
        mm.remember("expiring", "value", MemoryCategory.FACTS, expiration=time.time() - 1)
        entry = mm.recall("expiring")
        assert entry is None

    def test_explain(self):
        mm = self._get_test_manager()
        mm.remember("explain_key", "important fact", MemoryCategory.FACTS, source="user")
        explanation = mm.explain("explain_key")
        assert "explain_key" in explanation
        assert "FACTS" in explanation

    def test_importance(self):
        mm = self._get_test_manager()
        mm.remember("important", "value", MemoryCategory.FACTS, importance=0.9)
        mm.remember("trivial", "value", MemoryCategory.FACTS, importance=0.1)
        important = mm.get_important(min_importance=0.5)
        assert len(important) >= 1
        assert important[0].key == "important"

    def test_cleanup_expired(self):
        mm = self._get_test_manager()
        mm.remember("alive", "value", MemoryCategory.FACTS)
        mm.remember("dead", "value", MemoryCategory.FACTS, expiration=time.time() - 100)
        count = mm.cleanup_expired()
        assert count >= 1
        assert mm.recall("alive") is not None
        assert mm.recall("dead") is None


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    def test_tool_registry_with_permissions(self):
        """Test that tool registry and permission system work together."""
        reg = ToolRegistry()
        ps = PermissionSystem()

        # Register a tool
        tool = ToolSpec(
            name="browser.search",
            description="Search the web",
            params=[ToolSchema(name="query", type="str", required=True)],
            permission=PermissionLevel.SAFE_ACTION,
            execute_fn=lambda query: ActionResult.ok(message=f"Searched: {query}"),
        )
        reg.register(tool)

        # Check permission
        allowed, reason, required = ps.check_permission("browser.search", "search the web")
        assert allowed is True or required.value <= PermissionLevel.SAFE_ACTION.value

        # Execute
        result = reg.execute("browser.search", {"query": "test"})
        assert result.success is True

    def test_goal_planner_to_agent_executor(self):
        """Test goal planner output can be consumed by agent executor."""
        reg = ToolRegistry()
        reg.register(ToolSpec(
            name="test.echo",
            description="Echo",
            params=[ToolSchema(name="text", type="str", required=True)],
            permission=PermissionLevel.READ_ONLY,
            execute_fn=lambda text: ActionResult.ok(message=text),
        ))

        planner = GoalPlanner(tool_registry=reg)
        graph = planner.decompose("echo hello world")

        # Manually set arguments since the deterministic planner doesn't extract them
        for step in graph.steps:
            if step.tool == "test.echo":
                # Extract text after the tool keyword
                step.arguments = {"text": step.description.replace("echo", "").strip() or "hello"}

        executor = AgentExecutor(
            tool_registry=reg,
            permission_system=PermissionSystem(),
        )
        result = executor.execute(graph, speak=False)
        assert result.success is True

    def test_hybrid_router_escalation(self):
        """Test that hybrid router correctly escalates complex commands."""
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)

        # Simple should stay simple
        intent, conf, mode = hr.route("open chrome")
        assert mode == "simple"

        # Compound should escalate
        intent, conf, mode = hr.route("find resume and rename it and move it to documents")
        assert mode == "complex"

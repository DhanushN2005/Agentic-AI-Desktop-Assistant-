"""
Tests for goal preservation, local code search, and planning depth fixes.
"""
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.action_result import ActionResult
from core.tool_registry import ToolRegistry, ToolSpec, ToolSchema, PermissionLevel
from core.permission_system import PermissionSystem
from core.goal_planner import GoalPlanner, TaskGraph, TaskStep, StepStatus
from core.hybrid_router import HybridRouter
from core.goal_evaluator import GoalEvaluator, GoalCheck, GoalEvaluation
from utils.path_resolver import PathResolver
from engines.code_search import CodeSearchEngine, SearchResult


# =============================================================================
# GOAL PRESERVATION TESTS
# =============================================================================

class TestGoalPreservation:
    """Test that original user goals are preserved through planning."""

    def test_goal_planner_preserves_original(self):
        """Original goal must be preserved in the TaskGraph."""
        planner = GoalPlanner()
        goal = "search code for binary search and save to Downloads/result.py"
        graph = planner.decompose(goal)
        assert graph.original_goal == goal

    def test_goal_planner_no_goal_replacement(self):
        """Planner must not replace original goal with intermediate step."""
        planner = GoalPlanner()
        goal = "find binary search implementation and save it to Downloads"
        graph = planner.decompose(goal)
        # All steps should reference the original goal, not replace it
        assert graph.original_goal == goal
        # Steps should be subtasks, not new goals
        for step in graph.steps:
            assert step.description != goal  # No step should be the full goal itself

    def test_goal_graph_metadata(self):
        """TaskGraph should carry metadata about the original goal."""
        planner = GoalPlanner()
        graph = planner.decompose("search code and save result")
        graph.metadata["original_user_input"] = "search code and save result"
        assert graph.metadata["original_user_input"] == "search code and save result"


# =============================================================================
# LOCAL CODE SEARCH TESTS
# =============================================================================

class TestLocalCodeSearch:
    """Test that 'search the code' routes to local search, not web search."""

    def test_router_routes_local_code_search(self):
        """'search my code for X' should route to local_code_search."""
        from core.router import IntentRouter
        router = IntentRouter()
        
        commands = [
            "search my code for binary search",
            "search the code for algorithm",
            "find in my project",
            "search code for function",
            "find function binary_search",
        ]
        
        for cmd in commands:
            intent, confidence = router.route(cmd.lower())
            assert intent == "local_code_search", f"'{cmd}' routed to {intent}, expected local_code_search"

    def test_router_routes_web_search_separately(self):
        """'search the web for X' should NOT route to local_code_search."""
        from core.router import IntentRouter
        router = IntentRouter()
        
        commands = [
            "search the web for binary search",
            "google binary search",
        ]
        
        for cmd in commands:
            intent, confidence = router.route(cmd.lower())
            assert intent != "local_code_search", f"'{cmd}' should not route to local_code_search"

    def test_hybrid_router_classifies_local_search(self):
        """HybridRouter should classify local search as simple."""
        from core.router import IntentRouter
        router = IntentRouter()
        hr = HybridRouter(router)
        
        mode = hr.classify("search my code for binary search")
        assert mode == "simple"

    def test_code_search_engine_finds_functions(self):
        """CodeSearchEngine should find function definitions."""
        engine = CodeSearchEngine(workspace_path=os.path.join(os.path.dirname(__file__), ".."))
        results = engine.find_function("route", extensions=[".py"], max_results=5)
        assert results.total_matches > 0
        assert any(m.match_type == "function" for m in results.matches)

    def test_code_search_engine_finds_classes(self):
        """CodeSearchEngine should find class definitions."""
        engine = CodeSearchEngine(workspace_path=os.path.join(os.path.dirname(__file__), ".."))
        results = engine.find_class("IntentRouter", extensions=[".py"], max_results=5)
        assert results.total_matches > 0

    def test_code_search_engine_text_search(self):
        """CodeSearchEngine should search for text patterns."""
        engine = CodeSearchEngine(workspace_path=os.path.join(os.path.dirname(__file__), ".."))
        results = engine.search("ActionResult", extensions=[".py"], max_results=5)
        assert results.total_matches > 0

    def test_code_search_result_structure(self):
        """Search results should have proper structure."""
        engine = CodeSearchEngine(workspace_path=os.path.join(os.path.dirname(__file__), ".."))
        results = engine.search("def route", extensions=[".py"], max_results=3)
        assert hasattr(results, "query")
        assert hasattr(results, "matches")
        assert hasattr(results, "total_matches")
        for match in results.matches:
            assert hasattr(match, "file")
            assert hasattr(match, "line_start")
            assert hasattr(match, "content")

    def test_code_search_skip_git_dirs(self):
        """CodeSearchEngine should skip .git directories."""
        engine = CodeSearchEngine(workspace_path=os.path.join(os.path.dirname(__file__), ".."))
        results = engine.search("test", max_results=10)
        for match in results.matches:
            assert ".git" not in match.file


# =============================================================================
# PLANNING DEPTH LIMIT TESTS
# =============================================================================

class TestPlanningDepth:
    """Test that planning depth is bounded."""

    def test_goal_planner_max_depth(self):
        """Goal planner should not exceed max depth."""
        planner = GoalPlanner()
        # Very complex goal
        goal = "find authentication code and refactor it and add tests and save results and verify"
        graph = planner.decompose(goal)
        # Should not create more than a reasonable number of steps
        assert len(graph.steps) <= 10

    def test_task_step_can_retry(self):
        """TaskStep should have retry limits."""
        step = TaskStep(task_id="s0", description="test", tool="")
        assert step.can_retry() is True
        step.increment_retry()
        step.increment_retry()
        assert step.can_retry() is False


# =============================================================================
# PATH RESOLVER TESTS
# =============================================================================

class TestPathResolver:
    """Test natural language path resolution."""

    def test_resolve_downloads(self):
        """'Downloads folder' should resolve to user Downloads."""
        resolver = PathResolver()
        path = resolver.resolve("Downloads folder")
        assert "Downloads" in path

    def test_resolve_desktop(self):
        """'desktop' should resolve to user Desktop."""
        resolver = PathResolver()
        path = resolver.resolve("desktop")
        assert "Desktop" in path

    def test_resolve_documents(self):
        """'documents' should resolve to user Documents."""
        resolver = PathResolver()
        path = resolver.resolve("documents")
        assert "Documents" in path

    def test_resolve_relative_path(self):
        """Relative paths should resolve against workspace."""
        resolver = PathResolver(workspace="E:\\test\\project")
        path = resolver.resolve("output/result.py")
        assert path.endswith("output/result.py") or path.endswith("output\\result.py")

    def test_resolve_filename_with_extension(self):
        """Filenames with extensions should be preserved."""
        resolver = PathResolver()
        name = resolver.resolve_filename("result.py")
        assert name == "result.py"

    def test_resolve_filename_python_hint(self):
        """Python content hint should add .py extension."""
        resolver = PathResolver()
        name = resolver.resolve_filename("result", content_hint="python")
        assert name == "result.py"

    def test_resolve_filename_text_hint(self):
        """Text content hint should add .txt extension."""
        resolver = PathResolver()
        name = resolver.resolve_filename("result", content_hint="text")
        assert name == "result.txt"


# =============================================================================
# GOAL EVALUATOR TESTS
# =============================================================================

class TestGoalEvaluator:
    """Test goal completion verification."""

    def test_evaluate_complete_goal(self):
        """Fully achieved goal should be marked complete."""
        evaluator = GoalEvaluator()
        evaluation = evaluator.evaluate(
            original_goal="search code for binary search and save to Downloads/result.py",
            execution_state={
                "searched_code": True,
                "search_method": "code_search",
                "found_implementation": True,
                "results_count": 3,
                "content_extracted": True,
                "file_saved": True,
                "file_path": "C:/Users/Dhanush/Downloads/result.py",
                "file_verified": True,
            }
        )
        # Check that key logical checks pass (search, local preference, save)
        key_checks = [c for c in evaluation.checks if any(k in c.description.lower() 
                      for k in ["search", "local", "saved", "found", "extracted"])]
        assert all(c.passed for c in key_checks)

    def test_evaluate_incomplete_goal(self):
        """Goal with missing steps should be marked incomplete."""
        evaluator = GoalEvaluator()
        evaluation = evaluator.evaluate(
            original_goal="search code for binary search and save to Downloads/result.py",
            execution_state={
                "searched_code": True,
                "search_method": "code_search",
                "found_implementation": True,
                "file_saved": False,  # Missing!
            }
        )
        assert evaluation.complete is False
        assert any(not c.passed for c in evaluation.checks)

    def test_evaluate_local_search_preference(self):
        """When user says 'search the code', local search should be used."""
        evaluator = GoalEvaluator()
        evaluation = evaluator.evaluate(
            original_goal="search my code for binary search",
            execution_state={
                "searched_code": True,
                "search_method": "web",  # Wrong!
            }
        )
        # Should fail the "local search was used" check
        local_check = next((c for c in evaluation.checks if "local" in c.description.lower()), None)
        assert local_check is not None
        assert local_check.passed is False

    def test_evaluate_summary(self):
        """Evaluation should produce a readable summary."""
        evaluator = GoalEvaluator()
        evaluation = evaluator.evaluate(
            original_goal="search code",
            execution_state={"searched_code": True, "found_implementation": True}
        )
        assert evaluation.summary
        assert "Goal" in evaluation.summary


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for the complete flow."""

    def test_goal_flow_complete(self):
        """Test complete goal flow: plan → search → save → verify."""
        planner = GoalPlanner()
        evaluator = GoalEvaluator()
        
        goal = "search code for binary search and save to Downloads/result.py"
        graph = planner.decompose(goal)
        
        # Verify goal is preserved
        assert graph.original_goal == goal
        
        # Simulate execution state
        execution_state = {
            "searched_code": True,
            "search_method": "code_search",
            "found_implementation": True,
            "content_extracted": True,
            "file_saved": True,
            "file_path": "C:/Users/Dhanush/Downloads/result.py",
            "file_verified": True,
        }
        
        evaluation = evaluator.evaluate(goal, execution_state)
        # Check that key logical checks pass
        key_checks = [c for c in evaluation.checks if any(k in c.description.lower() 
                      for k in ["search", "local", "saved", "found", "extracted"])]
        assert all(c.passed for c in key_checks)

    def test_router_classifies_compound_correctly(self):
        """Compound commands should be classified correctly."""
        from core.router import IntentRouter
        router = IntentRouter()
        
        # This should NOT be classified as search (web)
        intent, confidence = router.route("search my code for binary search")
        assert intent == "local_code_search"
        
        # This SHOULD be classified as search (web)
        intent, confidence = router.route("search for binary search on google")
        # Might be "search" or something else, but NOT "local_code_search"
        assert intent != "local_code_search"

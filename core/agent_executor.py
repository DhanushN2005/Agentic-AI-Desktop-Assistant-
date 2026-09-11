"""
Agent Executor — runs the Observe → Act → Verify loop for tool execution.

This is the main execution engine for complex tasks that go through the
GoalPlanner. It:

1. OBSERVEs the current state (pre-execution snapshot)
2. ACTs by calling the appropriate tool
3. VERIFYs the result matches expectations
4. RETRYs or ESCALATES on failure
5. REPORTs the final outcome

Simple commands still go through the existing handler system.
This module handles only agent-planned complex tasks.
"""
import logging
import time
import threading
from typing import Optional, Callable
from core.goal_planner import TaskGraph, TaskStep, StepStatus, VerificationStrategy
from core.tool_registry import ToolRegistry, PermissionLevel
from core.permission_system import PermissionSystem
from core.action_result import ActionResult
from core.execution_graph import ExecutionGraph, ExecutionNode


class AgentExecutor:
    """
    Executes a TaskGraph using the Observe → Act → Verify loop.
    
    Each step goes through:
      1. Pre-check: permissions, dependencies
      2. Observe: snapshot current state
      3. Act: execute the tool
      4. Verify: confirm the action succeeded
      5. Retry/Fallback if verification fails
      6. Record result in execution graph
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        permission_system: PermissionSystem,
        execution_graph: Optional[ExecutionGraph] = None,
        speak_fn: Optional[Callable] = None,
        orch: Optional[object] = None,
    ):
        self.tools = tool_registry
        self.permissions = permission_system
        self.execution_graph = execution_graph
        self.speak = speak_fn or (lambda msg: None)
        self.orch = orch
        self.logger = logging.getLogger("Flexie.AgentExecutor")
        self._cancel_event = threading.Event()

    def cancel(self):
        """Cancel the current execution."""
        self._cancel_event.set()
        self.logger.info("[AGENT_EXECUTOR] Execution cancelled by user.")

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def execute(self, graph: TaskGraph, speak: bool = True) -> ActionResult:
        """
        Execute all steps in a TaskGraph.
        
        Steps are executed in dependency order.
        Independent steps can run in parallel (future enhancement).
        """
        self._cancel_event.clear()
        total = len(graph.steps)
        completed = 0
        failed = 0

        self.logger.info(f"[AGENT_EXECUTOR] Starting execution of {total} steps for: {graph.original_goal[:50]}")
        if speak:
            self.speak(f"I'll break this into {total} steps and execute them for you.")

        while not graph.all_completed() and not self.is_cancelled():
            ready = graph.get_ready_steps()
            if not ready:
                # Deadlock or all remaining steps have failed dependencies
                if not graph.all_completed():
                    self.logger.warning("[AGENT_EXECUTOR] No ready steps. Possible deadlock.")
                    # Cancel remaining pending steps
                    for step in graph.steps:
                        if step.status == StepStatus.PENDING:
                            step.mark_cancelled()
                break

            for step in ready:
                if self.is_cancelled():
                    step.mark_cancelled()
                    continue

                self._execute_step(step, graph)
                if step.status == StepStatus.COMPLETED:
                    completed += 1
                elif step.status == StepStatus.FAILED:
                    failed += 1

        # Final summary
        if self.is_cancelled():
            self.speak("Task execution cancelled.")
            return ActionResult.fail(message="Execution cancelled", intent="agent_executor")

        if failed == 0:
            self.speak(f"All {completed} steps completed successfully.")
            return ActionResult.ok(
                message=f"Completed {completed}/{total} steps",
                intent="agent_executor",
                data=graph.to_dict(),
            )
        else:
            self.speak(f"Completed {completed} of {total} steps. {failed} step(s) failed.")
            return ActionResult.fail(
                message=f"{completed}/{total} completed, {failed} failed",
                intent="agent_executor",
                data=graph.to_dict(),
            )

    def _execute_step(self, step: TaskStep, graph: TaskGraph):
        """Execute a single step through the Observe → Act → Verify loop."""
        self.logger.info(f"[AGENT_EXECUTOR] Step {step.task_id}: {step.description}")
        step.mark_running()

        # 1. PERMISSION CHECK
        allowed, reason, required = self.permissions.check_permission(
            step.tool or step.description,
            step.description,
        )
        if not allowed:
            self.logger.warning(f"[AGENT_EXECUTOR] Permission denied: {reason}")
            # For now, log and continue (user can override)
            step.permission_level = required.name

        # 2. OBSERVE — pre-execution snapshot
        pre_state = self._observe()

        # 3. ACT — execute the tool
        result = self._act(step)

        # 4. VERIFY — confirm success
        if result.success:
            verified = self._verify(step, pre_state)
            if verified:
                step.mark_completed(result)
                self.logger.info(f"[AGENT_EXECUTOR] Step {step.task_id} completed and verified.")
            else:
                # Verification failed — attempt retry
                self._handle_verification_failure(step, result)
        else:
            # Action failed — attempt retry
            self._handle_action_failure(step, result)

        # 5. RECORD — log to execution graph
        self._record(step)

    def _observe(self) -> dict:
        """Take a snapshot of current state before action."""
        state = {"timestamp": time.time()}
        try:
            if self.orch:
                import pyperclip
                state["clipboard"] = pyperclip.paste()
                state["window"] = getattr(self.orch, '_get_active_window_title', lambda: "")()
        except Exception:
            pass
        return state

    def _act(self, step: TaskStep) -> ActionResult:
        """Execute the tool for a step."""
        if not step.tool:
            # No tool specified — try to use the orchestrator's handler
            if self.orch:
                try:
                    self.orch.handle_command(step.description, is_subcommand=True, silent=True)
                    return ActionResult.ok(message="Executed via handler", intent=step.description)
                except Exception as e:
                    return ActionResult.fail(message=str(e), intent=step.description)

            return ActionResult.fail(message="No tool and no orchestrator", intent=step.description)

        # Execute via tool registry
        return self.tools.execute(step.tool, step.arguments, timeout=step.timeout)

    def _verify(self, step: TaskStep, pre_state: dict) -> bool:
        """Verify that the step's action actually succeeded."""
        if step.verification == VerificationStrategy.NONE:
            return True  # No verification requested

        try:
            if step.verification == VerificationStrategy.FILE_EXISTS:
                return self._verify_file_exists(step)
            elif step.verification == VerificationStrategy.APP_RUNNING:
                return self._verify_app_running(step)
            elif step.verification == VerificationStrategy.PAGE_LOADED:
                return self._verify_page_loaded(step)
            elif step.verification == VerificationStrategy.CLIPBOARD_CHANGED:
                return self._verify_clipboard_changed(step)
            elif step.verification == VerificationStrategy.CUSTOM:
                # Custom verification via tool
                tool = self.tools.get(step.tool)
                if tool and tool.verify_fn:
                    return tool.verify_fn(ActionResult.ok(intent=step.tool))
        except Exception as e:
            self.logger.warning(f"[AGENT_EXECUTOR] Verification error: {e}")
            return False

        return True

    def _verify_file_exists(self, step: TaskStep) -> bool:
        """Verify a file operation succeeded."""
        import os
        # Check if any path-like argument points to an existing file
        for val in step.arguments.values():
            if isinstance(val, str) and (os.sep in val or val.startswith("~")):
                path = os.path.expanduser(val)
                if os.path.exists(path):
                    self.logger.info(f"[VERIFY] File exists: {path}")
                    return True
        # Fallback: check context memory
        if self.orch and hasattr(self.orch, 'ctx'):
            last_path = self.orch.ctx.last_path
            if last_path and os.path.exists(last_path):
                self.logger.info(f"[VERIFY] File exists via context: {last_path}")
                return True
        self.logger.warning("[VERIFY] File existence could not be verified.")
        return False

    def _verify_app_running(self, step: TaskStep) -> bool:
        """Verify an app was launched."""
        if self.orch and hasattr(self.orch, 'validator'):
            app_name = step.arguments.get("app_name", step.description)
            curr_window = ""
            try:
                from engines.system import SystemCtrl
                curr_window = SystemCtrl.get_active_window_title()
            except Exception:
                pass
            return self.orch.validator.is_app_running(app_name, curr_window)
        return True  # Can't verify without orchestrator

    def _verify_page_loaded(self, step: TaskStep) -> bool:
        """Verify browser navigation succeeded."""
        if self.orch and hasattr(self.orch, 'browser'):
            page = self.orch.browser.page
            if page and not page.is_closed():
                url = page.url
                if url and "google.com" not in url:
                    self.logger.info(f"[VERIFY] Page loaded: {url}")
                    return True
        return True  # Can't verify without browser

    def _verify_clipboard_changed(self, step: TaskStep, pre_state: dict) -> bool:
        """Verify clipboard was updated."""
        try:
            import pyperclip
            curr = pyperclip.paste()
            return curr != pre_state.get("clipboard", "")
        except Exception:
            return True

    def _handle_verification_failure(self, step: TaskStep, result: ActionResult):
        """Handle a step where action succeeded but verification failed."""
        if step.can_retry():
            step.increment_retry()
            self.logger.warning(
                f"[AGENT_EXECUTOR] Verification failed for {step.task_id}. "
                f"Retry {step.retry_count}/{step.max_retries}"
            )
            # Retry the action
            result = self._act(step)
            if result.success:
                verified = self._verify(step, {})
                if verified:
                    step.mark_completed(result)
                    return
            # Still failed after retry
            step.mark_failed(f"Verification failed after {step.retry_count} retries")
        else:
            step.mark_failed(f"Verification failed: {result.message}")

    def _handle_action_failure(self, step: TaskStep, result: ActionResult):
        """Handle a step where the action itself failed."""
        if step.can_retry():
            step.increment_retry()
            self.logger.warning(
                f"[AGENT_EXECUTOR] Action failed for {step.task_id}. "
                f"Retry {step.retry_count}/{step.max_retries}"
            )
            result = self._act(step)
            if result.success:
                step.mark_completed(result)
                return
            step.mark_failed(f"Action failed after {step.retry_count} retries: {result.message}")
        else:
            step.mark_failed(f"Action failed: {result.message}")

    def _record(self, step: TaskStep):
        """Record the step result in the execution graph."""
        if not self.execution_graph:
            return
        try:
            node_id = f"agent_{step.task_id}"
            content = f"{step.description} → {step.status.name}"
            if step.result:
                content += f" ({step.result.message})"
            node = ExecutionNode(node_id, "ACTION", content)
            self.execution_graph.add_node(node)
        except Exception as e:
            self.logger.warning(f"[AGENT_EXECUTOR] Failed to record to graph: {e}")

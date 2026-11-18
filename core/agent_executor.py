"""
Agent Executor — runs the Observe → Act → Verify loop for tool execution.

This is the main execution engine for complex tasks that go through the
GoalPlanner. It:

1. OBSERVEs the current state (pre-execution snapshot, only what a check needs)
2. ACTs by calling the appropriate tool (typed call) or the handler pipeline
3. VERIFYs the result matches expectations (True / False / None = could not tell)
4. RETRYs failed actions, but never repeats an action whose effect cannot be undone
5. REPORTs the final outcome honestly (including what could not be confirmed)

Simple commands still go through the existing handler system.
This module handles only agent-planned complex tasks.
"""
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from urllib.parse import urlparse

from core.action_result import ActionResult
from core.execution_graph import ExecutionGraph, ExecutionNode
from core.goal_planner import StepStatus, TaskGraph, TaskStep, VerificationStrategy
from core.permission_system import PermissionLevel, PermissionSystem
from core.run_budget import RunBudget
from core.tool_registry import ToolRegistry

# Argument names that hold a filesystem path (checked by name, not by guessing from the value).
_PATH_ARG_NAMES = frozenset({
    "path", "file", "filename", "filepath", "file_path", "dest", "destination", "target",
    "output", "output_path", "save_path", "src", "source", "directory", "folder", "dir",
})
# Statuses the controller returns for a handler command that did NOT run to completion.
_HANDLER_FAIL_STATUSES = frozenset({"blocked", "awaiting_confirmation", "failed", "delegated", "cancelled"})


class AgentExecutor:
    """
    Executes a TaskGraph using the Observe → Act → Verify loop.

    Each step goes through:
      1. Pre-check: permissions, dependencies
      2. Observe: snapshot the state a check will need
      3. Act: execute the tool
      4. Verify: confirm the action succeeded
      5. Retry/Fallback when it is safe to repeat the action
      6. Record result in execution graph
    """

    APPROVAL_WAIT_SECONDS = 20.0

    def __init__(
        self,
        tool_registry: ToolRegistry,
        permission_system: PermissionSystem,
        execution_graph: ExecutionGraph | None = None,
        speak_fn: Callable | None = None,
        orch: object | None = None,
    ):
        self.tools = tool_registry
        self.permissions = permission_system
        self.execution_graph = execution_graph
        self._speak_fn = speak_fn or (lambda msg: None)
        self._speak_enabled = True
        self.orch = orch
        self.logger = logging.getLogger("Flexie.AgentExecutor")
        self._cancel_event = threading.Event()
        self.budget = RunBudget()

    # ------------------------------------------------------------------ speech / cancel
    @property
    def speak(self) -> Callable:
        """Callable that honours the ``speak`` flag of the current ``execute`` call."""
        return self._say

    def _say(self, msg: str) -> None:
        if self._speak_enabled:
            self._speak_fn(msg)

    def cancel(self):
        """Cancel the current execution."""
        self._cancel_event.set()
        self.logger.info("[AGENT_EXECUTOR] Execution cancelled by user.")

    def is_cancelled(self) -> bool:
        """Own cancel flag, or the orchestrator's per-command stop signal (cleared at each new
        command, so a stop issued for THIS command is honoured even if it arrived before
        ``execute`` started)."""
        if self._cancel_event.is_set():
            return True
        stop = getattr(self.orch, "stop_event", None)
        try:
            return bool(stop is not None and stop.is_set())
        except Exception:
            return False

    # ------------------------------------------------------------------------- execute
    def execute(self, graph: TaskGraph, speak: bool = True) -> ActionResult:
        """
        Execute all steps in a TaskGraph.

        Steps run in dependency order; a failed step cancels only the steps that depend on it.
        """
        self._cancel_event.clear()
        self._speak_enabled = bool(speak)
        self.budget = RunBudget()  # fresh limits for every plan
        total = len(graph.steps)

        self.logger.info(f"[AGENT_EXECUTOR] Starting execution of {total} steps for: {graph.original_goal[:50]}")
        self._say(f"I'll break this into {total} steps and execute them for you.")

        while not graph.all_completed() and not self.is_cancelled() and not self.budget.expired():
            ready = graph.get_ready_steps()
            if not ready:
                # Remaining steps depend on a failed/cancelled step: they can never run.
                self.logger.info("[AGENT_EXECUTOR] No runnable steps left; cancelling dependents of failed steps.")
                for step in graph.steps:
                    if step.status == StepStatus.PENDING:
                        step.mark_cancelled()
                break

            for step in ready:
                if self.is_cancelled() or self.budget.tripped or self.budget.expired():
                    step.mark_cancelled()
                    continue
                self._execute_step(step, graph)

        completed = sum(1 for s in graph.steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in graph.steps if s.status == StepStatus.FAILED)
        unconfirmed = sum(1 for s in graph.steps
                          if s.status == StepStatus.COMPLETED and s.verification != VerificationStrategy.NONE
                          and s.verified is not True)

        if self.budget.tripped:
            for st in graph.steps:
                if st.status == StepStatus.PENDING:
                    st.mark_cancelled()
            self.logger.warning(f"[AGENT_EXECUTOR] Run stopped: {self.budget.tripped}")
            self._say(f"I stopped this task: {self.budget.tripped}.")
            return ActionResult.fail(
                message=f"Stopped: {self.budget.tripped}", intent="agent_executor",
                data={**graph.to_dict(), "budget_tripped": self.budget.tripped},
            )

        if self.is_cancelled():
            for st in graph.steps:
                if st.status == StepStatus.PENDING:
                    st.mark_cancelled()
            self._say("Task execution cancelled.")
            return ActionResult.fail(message="Execution cancelled", intent="agent_executor",
                                     data=graph.to_dict())

        note = f" ({unconfirmed} could not be double-checked)" if unconfirmed else ""
        if failed == 0 and completed == total:
            self._say(f"All {completed} steps completed{note}.")
            return ActionResult.ok(
                message=f"Completed {completed}/{total} steps{note}",
                intent="agent_executor",
                data={**graph.to_dict(), "unconfirmed": unconfirmed},
            )
        cancelled = total - completed - failed
        self._say(f"Completed {completed} of {total} steps. {failed} failed"
                  f"{f', {cancelled} skipped' if cancelled else ''}.")
        return ActionResult.fail(
            message=f"{completed}/{total} completed, {failed} failed, {cancelled} skipped",
            intent="agent_executor",
            data={**graph.to_dict(), "unconfirmed": unconfirmed},
        )

    # --------------------------------------------------------------------- permissions
    def _needs_approval(self, step: TaskStep) -> bool:
        tool = self.tools.get(step.tool) if step.tool else None
        subject = tool if tool is not None else (step.tool or step.description)
        return not self.permissions.check_permission(subject, step.description)[0]

    def _ensure_permission(self, step: TaskStep) -> bool:
        """Return True only if the step is allowed (possibly after user approval)."""
        tool = self.tools.get(step.tool) if step.tool else None
        subject = tool if tool is not None else (step.tool or step.description)
        allowed, reason, required = self.permissions.check_permission(subject, step.description)
        if allowed:
            return True

        step.permission_level = required.name if required else None
        self.logger.warning(f"[AGENT_EXECUTOR] Permission required: {reason}")
        voice = getattr(self.orch, "voice", None)
        approved = self.permissions.await_approval(
            step.tool or step.description, step.description, required,
            voice_confirm=getattr(voice, "confirm", None),
            wait_seconds=self.APPROVAL_WAIT_SECONDS,
            is_cancelled=self.is_cancelled,
        )
        if approved:
            self.logger.info(f"[AGENT_EXECUTOR] Step {step.task_id} approved by user.")
            return True
        self.logger.warning(f"[AGENT_EXECUTOR] Step {step.task_id} denied (no approval): {reason}")
        step.mark_failed(f"Permission denied: {reason}")
        return False

    # ----------------------------------------------------------------------- one step
    def _execute_step(self, step: TaskStep, graph: TaskGraph):
        """Execute a single step through the Observe → Act → Verify loop."""
        self.logger.info(f"[AGENT_EXECUTOR] Step {step.task_id}: {step.description}")
        step.mark_running()

        # 1. PERMISSION CHECK — fail CLOSED. A denied step never runs unless the
        # user approves it (UI/API approval) within the approval window.
        needed_approval = self._needs_approval(step)
        try:
            if not self._ensure_permission(step):
                self._record(step)
                return

            # 2. OBSERVE — only the state this step's verification will compare against
            pre_state = self._observe(step)

            # 3. ACT — execute the tool
            result = self._act(step)

            # 4. VERIFY — confirm success
            if result.success:
                self._finish_after_success(step, result, pre_state)
            else:
                self._handle_action_failure(step, result, pre_state)
        finally:
            # An approval authorizes this one step only — even if something above raised.
            if needed_approval:
                self.permissions.consume_approval()

        # 5. RECORD — log to execution graph
        self._record(step)

    def _finish_after_success(self, step: TaskStep, result: ActionResult, pre_state: dict) -> None:
        verdict = self._verify(step, pre_state, result)
        step.verified = verdict if step.verification != VerificationStrategy.NONE else None
        if verdict is False:
            self._handle_verification_failure(step, result, pre_state)
            return
        if verdict is None and step.verification != VerificationStrategy.NONE:
            self.logger.info(f"[VERIFY] Step {step.task_id}: no evidence either way; accepting the tool's own success.")
        step.mark_completed(result)
        self.logger.info(f"[AGENT_EXECUTOR] Step {step.task_id} completed"
                         f"{' and verified' if verdict else ''}.")

    # ----------------------------------------------------------------------- observe/act
    def _observe(self, step: TaskStep) -> dict:
        """Snapshot only what the step's verification needs (no blanket clipboard reads)."""
        state = {"timestamp": time.time()}
        if step.verification == VerificationStrategy.CLIPBOARD_CHANGED:
            try:
                import pyperclip
                state["clipboard"] = pyperclip.paste()
            except Exception as _e:
                logging.debug("[agent_executor] clipboard snapshot unavailable: %s", _e)
        return state

    def _typed_tool(self, step: TaskStep):
        """The registered tool for this step if it can be called with the step's arguments."""
        if not step.tool:
            return None
        tool = self.tools.get(step.tool)
        if tool is None or not tool.enabled:
            return None
        ok, _err = tool.validate_args(step.arguments or {})
        return tool if ok else None

    def _act(self, step: TaskStep) -> ActionResult:
        """Execute a step: typed tool call when possible, else the handler pipeline."""
        reason = self.budget.charge(step.tool, step.arguments, step.description, key=step.task_id)
        if reason:
            return ActionResult.fail(message=f"Budget: {reason}", intent=step.description,
                                     data={"budget_tripped": reason})
        if self._typed_tool(step) is not None:
            return self.tools.execute(step.tool, step.arguments, timeout=step.timeout)

        # No usable typed call (unknown tool, or planner gave no arguments): route the
        # step's description through the normal handler pipeline, which has its own
        # safety/danger checks.
        if not self.orch:
            return ActionResult.fail(message="No typed tool and no orchestrator", intent=step.description)
        try:
            status = self.orch.handle_command(step.description, is_subcommand=True, silent=True)
        except Exception as e:
            logging.debug("[core/agent_executor.py] handler step failed: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent=step.description)
        # The controller reports deferred/blocked commands as status strings; those
        # did NOT run and must not be counted as success.
        if status is False or (isinstance(status, str) and status in _HANDLER_FAIL_STATUSES):
            return ActionResult.fail(message=str(status), intent=step.description)
        return ActionResult.ok(message="Executed via handler", intent=step.description,
                               data={"via_handler": True})

    # ---------------------------------------------------------------------------- retry
    def _repeatable(self, step: TaskStep, result: ActionResult | None = None) -> bool:
        """May this step's ACTION be run again?

        Re-running an action whose effect cannot be undone (send email, git commit, shell,
        file edits) because a check was inconclusive, or because we do not know whether the
        first attempt ran (timeout), would repeat the effect. Only read-only / reversible
        tools, and handler steps that explicitly reported failure, are repeated.
        """
        if result is not None and (result.data or {}).get("budget_tripped"):
            return False
        tool = self._typed_tool(step)
        if tool is None:
            # Handler-routed: repeat only a step that reported an explicit failure.
            return bool(result is not None and not result.success)
        idempotent = getattr(tool, "idempotent", None)
        if idempotent is None:
            idempotent = tool.permission.value <= PermissionLevel.SAFE_ACTION.value
        if result is not None and (result.data or {}).get("outcome_unknown") and not idempotent:
            return False
        return bool(idempotent)

    def _handle_verification_failure(self, step: TaskStep, result: ActionResult, pre_state: dict):
        """The action reported success but a definite check says the outcome is absent."""
        if step.can_retry() and self._repeatable(step, None):
            step.increment_retry()
            self.logger.warning(f"[AGENT_EXECUTOR] Verification failed for {step.task_id}. "
                                f"Retry {step.retry_count}/{step.max_retries}")
            retry = self._act(step)
            if retry.success and self._verify(step, self._observe(step), retry) is not False:
                step.verified = True
                step.mark_completed(retry)
                return
            step.mark_failed(f"Verification failed after {step.retry_count} retries")
        elif step.can_retry():
            step.mark_failed("Could not confirm the outcome, and the action is not safe to repeat "
                             "(it would repeat its effect).")
        else:
            step.mark_failed(f"Verification failed: {result.message}")

    def _handle_action_failure(self, step: TaskStep, result: ActionResult, pre_state: dict):
        """The action itself reported failure."""
        if step.can_retry() and self._repeatable(step, result):
            step.increment_retry()
            self.logger.warning(f"[AGENT_EXECUTOR] Action failed for {step.task_id}. "
                                f"Retry {step.retry_count}/{step.max_retries}")
            retry = self._act(step)
            if retry.success:
                # A retried success is verified exactly like a first-time success.
                self._finish_after_success(step, retry, pre_state)
                if step.status == StepStatus.RUNNING:
                    step.mark_failed(f"Action failed after {step.retry_count} retries: {result.message}")
                return
            step.mark_failed(f"Action failed after {step.retry_count} retries: {retry.message}")
        else:
            suffix = " (not retried: repeating it could repeat its effect)" if (
                step.can_retry() and (result.data or {}).get("outcome_unknown")) else ""
            step.mark_failed(f"Action failed: {result.message}{suffix}")

    # ---------------------------------------------------------------------- verification
    def _verify(self, step: TaskStep, pre_state: dict, result: ActionResult | None = None) -> bool | None:
        """True = confirmed, False = checked and the outcome is absent, None = could not tell."""
        if step.verification == VerificationStrategy.NONE:
            return True  # nothing requested
        try:
            if step.verification == VerificationStrategy.FILE_EXISTS:
                return self._verify_file_exists(step, pre_state)
            if step.verification == VerificationStrategy.APP_RUNNING:
                return self._verify_app_running(step)
            if step.verification == VerificationStrategy.PAGE_LOADED:
                return self._verify_page_loaded(step)
            if step.verification == VerificationStrategy.CLIPBOARD_CHANGED:
                return self._verify_clipboard_changed(step, pre_state)
            if step.verification == VerificationStrategy.DOM_ELEMENT:
                return self._verify_dom_element(step)
            if step.verification == VerificationStrategy.CUSTOM:
                tool = self.tools.get(step.tool) if step.tool else None
                if tool is not None and tool.verify_fn:
                    return bool(tool.verify_fn(result or ActionResult.ok(intent=step.tool)))
                return None
        except Exception as e:
            self.logger.warning(f"[AGENT_EXECUTOR] Verification error: {e}")
            return None  # a broken check is "could not tell", not proof of failure
        return None

    @staticmethod
    def _candidate_paths(step: TaskStep) -> list[str]:
        paths: list[str] = []
        for key, val in (step.arguments or {}).items():
            if not isinstance(val, str) or not val.strip():
                continue
            looks_like_path = (
                key.lower() in _PATH_ARG_NAMES
                or val.startswith("~")
                or re.match(r"^[A-Za-z]:[\\/]", val) is not None      # C:\x or C:/x
                or val.startswith(("\\\\", "./", ".\\", "../", "..\\"))
            )
            if looks_like_path:
                paths.append(os.path.abspath(os.path.expandvars(os.path.expanduser(val.strip()))))
        return paths

    def _verify_file_exists(self, step: TaskStep, pre_state: dict) -> bool | None:
        """The file the step was asked to produce exists (and is non-empty if content was given)."""
        paths = self._candidate_paths(step)
        if paths:
            for path in paths:
                if os.path.exists(path):
                    expected = (step.arguments or {}).get("content")
                    if isinstance(expected, str) and expected and os.path.isfile(path) and os.path.getsize(path) == 0:
                        self.logger.warning(f"[VERIFY] {path} exists but is empty although content was written.")
                        return False
                    self.logger.info(f"[VERIFY] File exists: {path}")
                    return True
            self.logger.warning(f"[VERIFY] Expected file not found: {paths}")
            return False
        # No path argument (e.g. a handler-style step): the orchestrator may know the last file
        # it touched — but only trust it if it was touched DURING this step, never a stale one.
        last = getattr(getattr(self.orch, "ctx", None), "last_path", None)
        started = pre_state.get("timestamp")
        if last and started and os.path.exists(last):
            try:
                if os.path.getmtime(last) >= started - 1.0:
                    return True
            except OSError:
                pass
        return None

    @staticmethod
    def _app_tokens(step: TaskStep) -> list[str]:
        args = step.arguments or {}
        for key in ("app_name", "name", "app", "application"):
            if isinstance(args.get(key), str) and args[key].strip():
                return [args[key].strip().lower()]
        for key in ("path", "file", "target"):
            if isinstance(args.get(key), str) and args[key].strip():
                base = os.path.splitext(os.path.basename(args[key].strip()))[0].lower()
                if base:
                    return [base]
        words = re.sub(r"\b(open|launch|start|run|the|a|an|app|application|program|please)\b", " ",
                       step.description.lower())
        return [w for w in re.findall(r"[a-z0-9][a-z0-9._+-]*", words)][:3]

    def _verify_app_running(self, step: TaskStep) -> bool | None:
        """The app's process is running or its window is up (either is enough)."""
        tokens = self._app_tokens(step)
        if not tokens:
            return None
        checked = False
        try:
            import psutil
            names = {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
            checked = True
            for token in tokens:
                if any(token in n for n in names):
                    return True
        except Exception as _e:
            logging.debug("[agent_executor] process list unavailable: %s", _e)
        validator = getattr(self.orch, "validator", None)
        if validator is not None:
            try:
                from engines.system import SystemCtrl
                title = SystemCtrl.get_active_window_title()
                checked = True
                if any(validator.is_app_running(t, title) for t in tokens):
                    return True
            except Exception as _e:
                logging.debug("[agent_executor] window title unavailable: %s", _e)
        return False if checked else None

    def _browser_page(self):
        browser = getattr(self.orch, "browser", None)
        return getattr(browser, "page", None) if browser is not None else None

    @staticmethod
    def _host(url: str) -> str:
        host = (urlparse(url if "://" in url else f"//{url}").hostname or "").lower()
        return host[4:] if host.startswith("www.") else host

    def _verify_page_loaded(self, step: TaskStep) -> bool | None:
        """The browser is on the page that was asked for (or at least on a real page)."""
        browser = getattr(self.orch, "browser", None)
        if browser is None:
            return None
        page = getattr(browser, "page", None)
        if page is None or (hasattr(page, "is_closed") and page.is_closed()):
            return False
        url = getattr(page, "url", "") or ""
        if url in ("", "about:blank") or url.startswith(("chrome-error://", "edge-error://")):
            return False
        target = (step.arguments or {}).get("url")
        if isinstance(target, str) and target.strip():
            want, got = self._host(target.strip()), self._host(url)
            if want and got:
                return got == want or got.endswith("." + want) or want.endswith("." + got)
        return True

    def _verify_clipboard_changed(self, step: TaskStep, pre_state: dict) -> bool | None:
        """The clipboard now differs from the snapshot taken before the step."""
        if "clipboard" not in pre_state:
            return None
        try:
            import pyperclip
            return pyperclip.paste() != pre_state["clipboard"]
        except Exception as _e:
            logging.debug("[agent_executor] clipboard unavailable: %s", _e)
            return None

    def _verify_dom_element(self, step: TaskStep) -> bool | None:
        """The expected element is present on the current page."""
        selector = (step.verification_args or {}).get("selector") or (step.arguments or {}).get("selector")
        page = self._browser_page()
        if not selector or page is None or (hasattr(page, "is_closed") and page.is_closed()):
            return None
        try:
            return page.query_selector(selector) is not None
        except Exception as _e:
            logging.debug("[agent_executor] DOM query failed: %s", _e)
            return None

    # -------------------------------------------------------------------------- record
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

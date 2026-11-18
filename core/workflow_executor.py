import logging
import os
import re
import threading
import time
import uuid

from core.action_result import ActionResult
from core.execution_graph import ExecutionNode
from core.run_budget import RunBudget
from core.task_classifier import TaskState
from engines.system import SystemCtrl


class WorkflowExecutor:
    """Executes multi-step workflows with state snapshots, verification, and self-healing recovery.

    Extracted from FlexieOrchestrator so the orchestrator stays a thin coordinator.
    All orchestrator dependencies are reached through the ``orch`` reference.
    """
    def __init__(self, orch):
        self.orch = orch
        # Human-readable reason for the last verification failure (None if last step verified).
        self.last_verify_reason: str | None = None

    def blocking_execute(self, cmd: str, timeout: float = None) -> ActionResult:
        """
        Queues a command and blocks until the action worker completes it.

        Uses threading.Event — NO busy-waiting (FIX 8).
        Returns an ActionResult with success/failure details (FIX 10).

        Per-action timeouts are resolved from ACTION_TIMEOUTS (FIX 11).
        """
        orch = self.orch
        # Normalize first so the timeout lookup uses the correct intent
        normalized = orch._normalize_dag_command(cmd)

        if timeout is None:
            _intent, _ = orch.router.route(normalized.lower().strip())
            timeout = orch.ACTION_TIMEOUTS.get(_intent, orch.ACTION_TIMEOUTS["default"])

        # The queue is drained by ONE worker thread. If we are already on it, queueing and
        # waiting would block the very thread that must run the command until the timeout
        # expires (and the command would then run late). Run it directly instead.
        if threading.get_ident() == getattr(orch, "_action_thread_id", None):
            return self._run_inline(cmd)

        done_event = threading.Event()
        result_holder = []

        orch.logger.info(f"[BLOCKING_EXECUTE] Scheduling '{cmd}' with timeout={timeout}s")
        # Push a tuple so _action_worker knows to signal completion (FIX 3)
        orch.cmd_queue.put((cmd, done_event, result_holder))

        # Wait — threading.Event.wait() releases the GIL; no CPU spin (FIX 8)
        if done_event.wait(timeout=timeout):
            return result_holder[0] if result_holder else ActionResult.ok(message="Completed", intent=cmd)

        orch.logger.error(f"[BLOCKING_EXECUTE] Timeout after {timeout}s for: '{cmd}'")
        return ActionResult.fail(message=f"Timeout after {timeout}s", intent=cmd)

    _FAIL_STATUSES = frozenset({"blocked", "awaiting_confirmation", "failed", "delegated", "cancelled"})

    def _run_inline(self, cmd: str, **kwargs) -> ActionResult:
        """Run a command on the calling (action) thread and report what really happened."""
        try:
            status = self.orch.handle_command(cmd, **kwargs)
        except Exception as e:
            return ActionResult.fail(message=str(e), intent=cmd)
        if status is False or (isinstance(status, str) and status in self._FAIL_STATUSES):
            return ActionResult.fail(message=str(status), intent=cmd)
        return ActionResult.ok(message="Executed", intent=cmd)

    def verify_step(self, step: str, pre_state: dict, intent: str, max_retries: int = 2):
        """
        Verifies that a workflow step executed successfully and attempts self-healing
        recovery up to max_retries times (FIX 14).

        Returns:
            (verified: bool, retries_used: int)
        """
        orch = self.orch
        step_lower = step.lower()
        verified = True
        retries = 0
        self.last_verify_reason = None

        # A. Verification for file/folder operations
        if "folder" in step_lower:
            last_path = orch.ctx.last_path
            if last_path and os.path.exists(last_path) and os.path.isdir(last_path):
                orch.logger.info(f"[PLANNER VERIFICATION SUCCESS] Folder exists: {last_path}")
            else:
                orch.logger.warning("[PLANNER VERIFICATION FAILURE] Folder creation could not be verified. Recovering...")
                verified = False
                while retries < max_retries and not verified:
                    orch.files.create_folder(step)
                    time.sleep(0.5)
                    if orch.ctx.last_path and os.path.isdir(orch.ctx.last_path):
                        verified = True
                        orch.logger.info("[PLANNER RECOVERY SUCCESS] Folder re-creation succeeded.")
                    retries += 1

        elif any(x in step_lower for x in ["create file", "write a file", "create document",
                                            "save file", "file_save", "write document",
                                            "code", "generate", "research", "save to", "binary search"]):
            active_doc = orch.ctx.active_document or orch.ctx.last_path
            if active_doc and os.path.exists(active_doc) and os.path.getsize(active_doc) > 0:
                orch.logger.info(f"[PLANNER VERIFICATION SUCCESS] File exists and non-empty: {active_doc}")
            elif orch.ctx.last_path and os.path.exists(orch.ctx.last_path) and os.path.getsize(orch.ctx.last_path) > 0:
                orch.logger.info(f"[PLANNER VERIFICATION SUCCESS] File exists: {orch.ctx.last_path}")
            else:
                orch.logger.warning("[PLANNER VERIFICATION FAILURE] File creation/writing could not be verified. Recovering...")
                verified = False
                # Self-correction: try GoalEvaluator if available
                try:
                    from core.goal_evaluator import GoalEvaluator
                    ge = GoalEvaluator()
                    eval_res = ge.evaluate(step, {"file_saved": False, "file_path": active_doc or ""})
                    orch.logger.info(f"[SELF-CORRECTION] Goal evaluator: {eval_res.summary}")
                except Exception as _e:
                    logging.debug("[core/workflow_executor.py:99] Swallowed exception: %s: %s", type(_e).__name__, _e)
                # Recovery: Copy contents to clipboard and tell user, but the
                # step still FAILED verification — never mark it verified.
                if orch.ctx.last_response:
                    try:
                        import pyperclip
                        pyperclip.copy(orch.ctx.last_response)
                    except Exception as _e:
                        logging.debug("[core/workflow_executor.py:105] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    orch.speak("Verification Alert: Document writing failed. I saved the response to clipboard so you can paste it manually.")
                self.last_verify_reason = (
                    f"file step unverified: '{active_doc or orch.ctx.last_path or step}' "
                    "missing or empty after execution"
                )
                orch.logger.warning(f"[PLANNER VERIFICATION FAILURE] {self.last_verify_reason}")
                retries += 1

        # B. Verification for browser operations
        elif any(x in step_lower for x in ["navigate", "open website", "go to"]):
            if hasattr(orch, 'browser') and orch.browser.page and not orch.browser.page.is_closed():
                curr_url = orch.browser.page.url
                if curr_url and "google.com" not in curr_url:
                    orch.logger.info(f"[PLANNER VERIFICATION SUCCESS] Browser navigated to: {curr_url}")
                else:
                    orch.logger.warning("[PLANNER VERIFICATION FAILURE] Browser navigation failed or stalled. Resetting context...")
                    verified = False
                    while retries < max_retries and not verified:
                        # Healing: Reset Playwright persistent context and retry
                        orch.browser.page = None
                        orch.browser.context = None
                        orch.browser.browser = None
                        orch.browser.navigate(step)
                        retries += 1
                        time.sleep(1.0)
                        if orch.browser.is_healthy():
                            verified = True
                            orch.logger.info("[PLANNER RECOVERY SUCCESS] Browser context reset successfully navigated.")

        elif "click" in step_lower:
            # Checked by standard click element which falls back to visual click on fail.
            pass

        # C. Verification for app operations
        elif any(x in step_lower for x in ["open", "launch", "run"]):
            curr_window = SystemCtrl.get_active_window_title()
            app_name = re.sub(r"(open|run|launch|start|the|app)", "", step_lower).strip()
            if app_name == "camera":
                is_app_active = orch.capability_validator.validate("camera", step_lower, pre_state)
            else:
                is_app_active = orch.validator.is_app_running(app_name, curr_window)

            if is_app_active:
                orch.logger.info(f"[PLANNER VERIFICATION SUCCESS] App window activated: {curr_window}")
            else:
                orch.logger.warning("[PLANNER VERIFICATION FAILURE] App window activation not detected. Healing...")
                verified = False
                while retries < max_retries and not verified:
                    # Tap ALT to release focus and retry
                    import pyautogui
                    pyautogui.press('alt')
                    time.sleep(0.3)
                    orch.files.open_item(step)
                    time.sleep(1.0)
                    retries += 1
                    curr_window = SystemCtrl.get_active_window_title()
                    if app_name == "camera":
                        is_app_active = orch.capability_validator.validate("camera", step_lower, pre_state)
                    else:
                        is_app_active = orch.validator.is_app_running(app_name, curr_window)
                    if is_app_active:
                        verified = True
                        orch.logger.info("[PLANNER RECOVERY SUCCESS] App focused on retry.")

        # D. Verification for clipboard
        elif "copy" in step_lower:
            curr_clip = SystemCtrl.get_clipboard()
            if curr_clip != pre_state["clipboard"]:
                orch.logger.info("[PLANNER VERIFICATION SUCCESS] Clipboard updated successfully.")
            else:
                orch.logger.warning("[PLANNER VERIFICATION FAILURE] Clipboard copy not verified. Retrying copy...")
                verified = False
                while retries < max_retries and not verified:
                    if orch.ctx.last_response:
                        import pyperclip
                        pyperclip.copy(orch.ctx.last_response)
                        verified = True
                        orch.logger.info("[PLANNER RECOVERY SUCCESS] Clipboard updated on manual retry.")
                    retries += 1

        return verified, retries

    def log_step_result(self, workflow_id: str, step_num: int, total: int,
                        intent: str, duration: float, verified: bool, retries: int):
        """
        Emits a structured, correlated log entry for each workflow step (FIX 13).

        Format:
            [Workflow <id>] Step N/T | Intent: <intent> | Duration: Xs |
            Verification: Passed/Failed | Retries: N
        """
        status = "Passed" if verified else "Failed"
        self.orch.logger.info(
            f"[Workflow {workflow_id}] Step {step_num}/{total} | "
            f"Intent: {intent} | Duration: {duration:.2f}s | "
            f"Verification: {status} | Retries: {retries}"
        )

    def execute(self, steps, depth: int = 0):
        """Executes a list of steps sequentially with system state snapshots, verification hooks, and self-healing recovery."""
        orch = self.orch

        if not steps or len(steps) == 0:
            orch.logger.warning("[WorkflowExecutor] Empty steps provided. Skipping execution.")
            return

        # Acquire arbitration lock for the main orchestrator agent
        lock_id = "workflow_execution"
        if not orch.arbitrator.acquire_lock(lock_id, "main_orchestrator", timeout=3.0):
            orch.logger.error("[ARBITRATOR] Could not acquire lock for workflow execution. Another agent is running.")
            orch.speak("I'm still busy with another task, so I couldn't start that plan. Please try again in a moment.")
            return False

        try:
            orch.speak(f"Initializing semantic plan with {len(steps)} sequential steps.")
            try:
                orch.send_to_ui("WORKFLOW", "|".join(steps))
            except Exception as _e:
                logging.debug("[core/workflow_executor.py:214] Swallowed exception: %s: %s", type(_e).__name__, _e)

            # ONE execution path for every plan size. (A separate "DAG" path for plans of 4 steps or
            # fewer used to run here; it deadlocked on the single action worker and skipped
            # verification and reporting, so behaviour also changed with the step count.)
            # FIX 13: Short workflow ID for correlated log entries across all steps
            workflow_id = str(uuid.uuid4())[:8]
            total_steps = len(steps)
            failed_steps = []        # the step itself failed or raised: eligible for ONE rephrased retry
            unconfirmed_steps = []   # ran, but the heuristic check could not confirm it: never re-run
            completed_count = 0
            budget = RunBudget()

            for idx, step in enumerate(steps):  # FIX 1: ALL execution logic is now INSIDE the loop
                task_state = TaskState.PENDING
                step_start_time = time.time()
                retries = 0
                step_intent = "unknown"  # FIX 5: track intent for adaptive router

                # Clean up LLM hallucinations where it prepends "Step 1:" to the string itself
                clean_step = re.sub(r"(?i)^step\s+\d+[\.:]?\s*", "", step).strip()

                # FIX 5: Resolve intent early so adaptive router learns the correct
                # mapping (e.g. "open notepad" → "app_op", not "open notepad" → "open notepad").
                try:
                    step_intent, _ = orch.router.route(clean_step.lower().strip())
                    if step_intent == "conversational":
                        _di, _, _ = orch.router.route_dynamic(clean_step, orch.brain)
                        if _di and _di != "conversational":
                            step_intent = _di
                except Exception as _e:
                    logging.debug("[core/workflow_executor.py:254] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    pass  # Non-fatal; fall back to "unknown"

                # Honour a stop request and the run limits between steps (identical consecutive steps
                # are legitimate - "press next" five times - so only a real loop trips the guard).
                stop = getattr(orch, "stop_event", None)
                if stop is not None and stop.is_set():
                    orch.speak("Stopping the plan as requested.")
                    break
                tripped = budget.charge("", {}, clean_step, key=f"wf-step-{idx}")
                if tripped:
                    orch.logger.warning(f"[Workflow {workflow_id}] stopped: {tripped}")
                    orch.speak(f"I stopped the plan: {tripped}.")
                    failed_steps = []
                    break

                # Watchdog Heartbeat Update
                orch.last_command_time = time.time()

                orch.speak(f"Step {idx + 1}: {clean_step}")
                orch.logger.info(f"[Workflow {workflow_id}] Step {idx + 1}/{total_steps}: '{clean_step}' (Intent: {step_intent})")
                task_state = TaskState.RUNNING

                # Take pre-execution state snapshot
                pre_state = {
                    "clipboard": SystemCtrl.get_clipboard(),
                    "window": SystemCtrl.get_active_window_title(),
                    "url": orch.browser.page.url if (hasattr(orch, 'browser') and orch.browser.page and not orch.browser.page.is_closed()) else None
                }

                # Execute step (FIX 15: catch per-step errors — do NOT abort entire workflow)
                action_failed = False
                try:
                    outcome = orch.handle_command(clean_step, is_subcommand=True, silent=True, source="planner", depth=depth)
                    if outcome is False or (isinstance(outcome, str) and outcome in self._FAIL_STATUSES):
                        action_failed = True
                        orch.logger.warning(f"[Workflow {workflow_id}] Step {idx + 1} reported: {outcome}")
                except Exception as e:
                    action_failed = True
                    orch.logger.error(f"[Workflow {workflow_id}] Step {idx + 1} execution error: {e}")
                    orch.logger.info(f"[FAILED] {clean_step}")
                    orch.speak("Step execution error. Attempting self-healing recovery.")

                # Wait a brief moment for state propagation
                time.sleep(1.0)

                # Post-execution verification & self-healing cascade (FIX 14: extracted to verify_step)
                verified, retries = self.verify_step(clean_step, pre_state, step_intent)

                # --- PHASE 1: Semantic Validator Check ---
                try:
                    # Basic non-blocking semantic validation wrapper
                    semantic_res = orch.semantic_validator.validate_outcome(clean_step, {"status": "executed"})
                    if not semantic_res.get("valid", True):
                        orch.logger.warning(f"[SEMANTIC_VALIDATOR] Flagged potential execution issue: {semantic_res.get('reason')}")
                except Exception as _e:
                    logging.debug("[core/workflow_executor.py:297] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    pass  # Safe fallback

                if verified and not action_failed:
                    task_state = TaskState.COMPLETED
                else:
                    task_state = TaskState.FAILED

                step_end_time = time.time()
                step_duration = step_end_time - step_start_time

                # Post-execution Critique
                report = orch.task_critic.critique(clean_step, step_start_time, step_end_time, verified, retries)

                # --- PHASE 1: Recovery Agent Hook ---
                if report.quality_score < 50.0:
                    try:
                        from recovery.analyzer import get_analyzer
                        recovery_agent = get_analyzer(orch.brain)
                        # Use diagnose_failure which takes cmd and error_msg
                        diagnosis = recovery_agent.diagnose_failure(clean_step, str(report))
                        orch.logger.info(f"[RECOVERY_AGENT] Diagnosis: {diagnosis.get('mitigation')}")
                    except Exception as e:
                        orch.logger.warning(f"[RECOVERY_AGENT] Integration fallback. {e}")

                # Log to Execution Graph
                node_id = str(uuid.uuid4())
                orch.execution_graph.add_node(ExecutionNode(node_id, "ACTION", clean_step))
                res_node_id = str(uuid.uuid4())
                res_node = ExecutionNode(res_node_id, "RESULT", "COMPLETED" if task_state == TaskState.COMPLETED else "FAILED")
                res_node.add_edge(node_id, "result_of")
                orch.execution_graph.add_node(res_node)

                learnable = step_intent not in ("unknown", "conversational", "", None)
                if task_state == TaskState.FAILED and action_failed:
                    orch.speak(f"Step {idx + 1} did not work. I'll try another way at the end.")
                    orch.logger.warning(f"[Workflow {workflow_id}] Step {idx + 1}/{total_steps} FAILED (action).")
                    if learnable:
                        orch.adaptive_router.record_route(clean_step, step_intent, False)  # FIX 5: intent, not clean_step
                    failed_steps.append(clean_step)
                elif task_state == TaskState.FAILED:
                    # The action ran without error; only the heuristic check was inconclusive.
                    # Re-running it could repeat a real effect, so report it instead.
                    orch.speak(f"Step {idx + 1} ran, but I couldn't confirm it worked.")
                    orch.logger.warning(f"[Workflow {workflow_id}] Step {idx + 1}/{total_steps} unconfirmed.")
                    unconfirmed_steps.append(clean_step)
                else:
                    completed_count += 1
                    orch.logger.info(f"[COMPLETE] {clean_step}")
                    orch.logger.info(f"[Workflow {workflow_id}] Step {idx + 1}/{total_steps} COMPLETED in {step_duration:.2f}s.")
                    if learnable:  # only learn routes from steps that really succeeded and were confirmed
                        orch.adaptive_router.record_route(clean_step, step_intent, True)   # FIX 5: intent, not clean_step

                # FIX 13: Emit structured step result entry
                self.log_step_result(
                    workflow_id, idx + 1, total_steps,
                    step_intent, step_duration, verified, retries
                )

            # Final self-correction: retry failed steps once with alternative via GoalEvaluator
            if failed_steps:
                orch.logger.warning(f"[SELF-CORRECTION] Workflow {workflow_id} had {len(failed_steps)} failed steps: {failed_steps}")
                orch.speak(f"Retrying {len(failed_steps)} failed steps with alternative approach.")
                for fstep in failed_steps:
                    try:
                        # Try alternative phrasing via brain
                        alt = orch.brain.ask(f"Rephrase this task for a desktop assistant to succeed: '{fstep}'. Return only the rephrased command.", system_override="You are a task rephraser. Return only the command.") if hasattr(orch, 'brain') else fstep
                        alt = alt.strip().split('\n')[0][:120] if alt else fstep
                        orch.logger.info(f"[SELF-CORRECTION RETRY] {fstep} -> {alt}")
                        orch.handle_command(alt, is_subcommand=True, silent=True, depth=depth+1)
                        time.sleep(0.5)
                    except Exception as e:
                        orch.logger.warning(f"[SELF-CORRECTION] Retry failed for {fstep}: {e}")
                # Final GoalEvaluator check if available
                try:
                    from core.goal_evaluator import GoalEvaluator
                    ge = GoalEvaluator()
                    # Build execution state from context
                    state = {"file_saved": bool(orch.ctx.last_path and os.path.exists(orch.ctx.last_path)), "file_path": orch.ctx.last_path or ""}
                    orig = " and ".join(steps)
                    eval_res = ge.evaluate(orig, state)
                    orch.logger.info(f"[GoalEvaluator] {eval_res.summary}")
                except Exception as _e:
                    logging.debug("[core/workflow_executor.py:369] Swallowed exception: %s: %s", type(_e).__name__, _e)

            # Tell the user how it went (this path used to end silently).
            problems = len(failed_steps) + len(unconfirmed_steps)
            if problems == 0 and completed_count:
                orch.speak(f"Done. All {completed_count} steps completed.")
            elif completed_count or problems:
                orch.speak(f"Finished {completed_count} of {total_steps} steps"
                           f"{f'; {len(failed_steps)} did not work' if failed_steps else ''}"
                           f"{f'; {len(unconfirmed_steps)} could not be confirmed' if unconfirmed_steps else ''}.")
            return not failed_steps

        finally:
            orch.arbitrator.release_lock(lock_id, "main_orchestrator")

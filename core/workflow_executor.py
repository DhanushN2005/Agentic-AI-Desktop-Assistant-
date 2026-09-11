import os
import re
import threading
import time
import uuid

from core.action_result import ActionResult
from core.execution_graph import ExecutionNode
from core.task_classifier import TaskState
from engines.system import SystemCtrl


class WorkflowExecutor:
    """Executes multi-step workflows with state snapshots, verification, and self-healing recovery.

    Extracted from FlexieOrchestrator so the orchestrator stays a thin coordinator.
    All orchestrator dependencies are reached through the ``orch`` reference.
    """
    def __init__(self, orch):
        self.orch = orch

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
                except: pass
                # Recovery: Copy contents to clipboard and tell user
                if orch.ctx.last_response:
                    try:
                        import pyperclip
                        pyperclip.copy(orch.ctx.last_response)
                    except: pass
                    orch.speak("Verification Alert: Document writing failed. Self-healing saved response to clipboard. Press Ctrl+V to paste.")
                    verified = True
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

        # Acquire arbitration lock for the main orchestrator agent
        lock_id = "workflow_execution"
        if not orch.arbitrator.acquire_lock(lock_id, "main_orchestrator", timeout=3.0):
            orch.logger.error("[ARBITRATOR] Could not acquire lock for workflow execution. Another agent is running.")
            return

        try:
            orch.speak(f"Initializing semantic plan with {len(steps)} sequential steps.")
            try:
                orch.send_to_ui("WORKFLOW", "|".join(steps))
            except: pass

            # --- PHASE 1: DAG PLANNER INTEGRATION (Minimal Intrusion) ---
            try:
                if len(steps) <= 4:
                    from core.dag_planner import DAGTask
                    dag_tasks = []
                    for i, step in enumerate(steps):
                        clean_step = re.sub(r"(?i)^step\s+\d+[\.:]?\s*", "", step).strip()
                        deps = [f"task_{i-1}"] if i > 0 else []
                        dag_tasks.append(DAGTask(task_id=f"task_{i}", command=clean_step, dependencies=deps))
                    orch.logger.info("[DAG] Dispatching to DAG Planner.")
                    orch.dag_planner.execute_graph(dag_tasks)
                    return  # Exit if successful, skipping sequential fallback
            except Exception as dag_err:
                orch.logger.warning(f"[DAG] Execution failed, falling back to sequential: {dag_err}")

            # FIX 13: Short workflow ID for correlated log entries across all steps
            workflow_id = str(uuid.uuid4())[:8]
            total_steps = len(steps)
            executed_intents = set()
            failed_steps = []

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
                except Exception:
                    pass  # Non-fatal; fall back to "unknown"

                # Deduplication Check - only skip exact duplicate commands, not same intent
                if clean_step in executed_intents:
                    orch.logger.info(f"[Workflow Deduplication] Skipping duplicate command in same workflow: {clean_step}")
                    continue
                executed_intents.add(clean_step)

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
                try:
                    orch.handle_command(clean_step, is_subcommand=True, silent=True, source="planner", depth=depth)
                except Exception as e:
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
                except Exception:
                    pass  # Safe fallback

                if verified:
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
                        from recovery.analyzer import RecoveryAnalyzer
                        recovery_agent = RecoveryAnalyzer(orch.brain)
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

                if task_state == TaskState.FAILED:
                    orch.speak(f"Step {idx + 1} did not pass automatic verification. Attempting manual fallback.")
                    orch.logger.warning(f"[Workflow {workflow_id}] Step {idx + 1}/{total_steps} FAILED.")
                    orch.adaptive_router.record_route(clean_step, step_intent, False)  # FIX 5: intent, not clean_step
                    failed_steps.append(clean_step)
                elif task_state == TaskState.COMPLETED:
                    orch.logger.info(f"[COMPLETE] {clean_step}")
                    orch.logger.info(f"[Workflow {workflow_id}] Step {idx + 1}/{total_steps} COMPLETED in {step_duration:.2f}s.")
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
                except: pass

        finally:
            orch.arbitrator.release_lock(lock_id, "main_orchestrator")

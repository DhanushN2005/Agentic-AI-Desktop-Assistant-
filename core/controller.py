import json
import logging
import os
import threading
import time

from core.danger_gate import DangerGate
from core.safety import SafetyGuard
from core.telemetry import Telemetry
from core.tool_registry import PermissionLevel
from engines.long_term_memory import GlobalMemory
from utils.config import Config
from utils.lazy import LazyModule

pyautogui = LazyModule("pyautogui")  # imported on first use (~1 s)


class FlexieController:
    """The Agentic Exoskeleton. Wraps the Orchestrator with Production layers."""
    def __init__(self, orchestrator, original_handle):
        self.orch = orchestrator
        self.original_handle = original_handle
        self.telemetry = Telemetry()
        self.safety = SafetyGuard()
        self.danger_gate = DangerGate()
        self.permission_system = getattr(self.orch, "permission_system", None)
        self.long_term = GlobalMemory()
        self.logger = logging.getLogger("Flexie.Controller")

        # P0 Feature 1: Continuous Conversation Mode
        self.last_command_time = time.time()
        threading.Thread(target=self._conversation_watchdog, daemon=True).start()

        # Danger Gate: command awaiting explicit user confirmation (or None)
        self.pending_confirmation = None
        self.pending_request_id = None   # id of the approval request this confirmation answers
        self.pending_since = 0.0         # monotonic time the question was asked

        # P0 Feature 2: Workspace Memory
        self.workspace_state = {
            "current_app": None,
            "current_project": None,
            "current_file": None
        }

        # Mode States
        self.dictation_active = False
        self.meeting_active = False

        # Load Macros
        self.macros = self._load_macros()

    def _load_macros(self):
        try:
            if os.path.exists("macros.json"):
                with open("macros.json") as f:
                    return json.load(f)
        except Exception as _e:
            logging.debug("[core/controller.py:52] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass
        return {
            "start coding mode": ["open vscode", "open browser"],
            "research mode": ["open browser", "new tab"]
        }

    def _conversation_watchdog(self):
        while True:
            time.sleep(5)
            self._expire_pending()
            if self.orch.active and (time.time() - self.last_command_time > 30):
                self.orch.active = False
                # Never let a stale confirmation silently expire into an
                # unrelated future command being mistaken for "confirm".
                self._clear_pending(reject=True)
                if not self.dictation_active and not self.meeting_active:
                    self.logger.info("Session closed due to inactivity.")

    PENDING_TTL_SECONDS = 60.0

    def _clear_pending(self, reject: bool = False) -> None:
        rid = self.pending_request_id
        self.pending_confirmation = None
        self.pending_request_id = None
        if reject and rid and self.permission_system:
            self.permission_system.reject_request(rid)

    def _expire_pending(self) -> bool:
        """Drop a confirmation question nobody answered in time, so a stray 'ok' said much
        later can never execute an old, forgotten delete."""
        if self.pending_confirmation and time.monotonic() - self.pending_since > self.PENDING_TTL_SECONDS:
            self.logger.info("Pending confirmation expired: %r", self.pending_confirmation)
            self._clear_pending(reject=True)
            return True
        return False

    def _smart_followup(self, command: str) -> str:
        cmd_lower = command.lower()

        # Track Workspace Memory
        if "open vscode" in cmd_lower or "open visual studio" in cmd_lower:
            self.workspace_state["current_app"] = "VSCode"
        elif "open youtube" in cmd_lower:
            self.workspace_state["current_app"] = "YouTube"
        elif "open browser" in cmd_lower or "open chrome" in cmd_lower:
            self.workspace_state["current_app"] = "Browser"

        # Smart Follow-up Preprocessor
        if "search" in cmd_lower and "youtube" not in cmd_lower and self.workspace_state["current_app"] == "YouTube":
            return command + " on YouTube"
        if "explain this file" in cmd_lower and self.workspace_state["current_project"]:
            return command + f" in {self.workspace_state['current_project']}"

        return command

    def execute(self, command: str, *args, **kwargs):
        """Processes a command through the safety and telemetry pipeline.

        Extra arguments (is_subcommand, silent, source, depth) belong to the wrapped
        orchestrator handler and are forwarded unchanged. Dropping them made planned
        sub-steps look like fresh top-level commands and re-planned them recursively.
        """
        self.last_command_time = time.time()
        self._handler_args = (args, kwargs)

        # DANGER GATE: an earlier high-impact command awaits user confirmation.
        if self.pending_confirmation and self._expire_pending():
            self.orch.speak("That confirmation timed out, so I did not run it.")
        if self.pending_confirmation:
            return self._handle_confirmation(command)

        # P0 Feature 10: Dictation Mode Bypass
        if self.dictation_active:
            if "stop dictation" in command.lower() or "end dictation" in command.lower():
                self.dictation_active = False
                self.orch.speak("Dictation mode ended.")
                return
            else:
                # Formatting commands
                cmd_l = command.lower()
                if cmd_l in ["new line", "newline"]:
                    pyautogui.press('enter')
                elif cmd_l == "comma":
                    pyautogui.write(", ")
                elif cmd_l in ["full stop", "period"]:
                    pyautogui.write(". ")
                elif cmd_l == "new paragraph":
                    pyautogui.press(['enter', 'enter'])
                else:
                    pyautogui.write(command + " ")
                return

        # Handle Dictation Trigger
        if "start dictation" in command.lower() or "dictation mode" in command.lower():
            self.dictation_active = True
            self.orch.speak("Dictation mode started. I will type whatever you say into the active window.")
            return

        # P0 Feature 9: Meeting Mode
        if "start meeting mode" in command.lower():
            self.meeting_active = True
            self.orch.speak("Meeting mode activated. I am now transcribing the conversation and extracting action items. Say 'Stop meeting mode' to finish.")
            return

        if self.meeting_active:
            if "stop meeting mode" in command.lower() or "end meeting mode" in command.lower():
                self.meeting_active = False
                self.orch.speak("Meeting ended. Generating summary and action items...")
                # Pseudo-logic to compile the transcript stored in memory
                context_getter = getattr(self.orch.memory, "get_conversation_messages", None)
                if callable(context_getter):
                    transcript = "\n".join(
                        f"{item.get('role', 'user')}: {item.get('content', '')}"
                        for item in context_getter(limit=20)
                    )
                else:
                    transcript = self.orch.memory.get_context(limit=20)
                summary = self.orch.brain.ask(f"Summarize this meeting transcript and extract tasks:\n{transcript}")
                with open("flexie_meeting_summary.md", "w") as f:
                    f.write(summary)
                self.orch.speak("Meeting summary saved to your workspace.")
                return
            else:
                # Just log the transcript quietly
                self.orch.memory.add("transcript", command)
                return

        # P0 Feature 6: Voice Notes
        if command.lower().startswith("take a note") or command.lower().startswith("remember this"):
            note = command.lower().replace("take a note", "").replace("remember this", "").strip()
            if not note:
                self.orch.speak("What should I note down?")
            else:
                self.orch.brain.vector_store.add_episode(f"note_{time.time()}", f"User Note: {note}")
                self.orch.speak("Note saved.")
            return

        # P0 Feature 7: Voice Memory Search
        if "what did we discuss" in command.lower() or "search memory" in command.lower() or "what did i save" in command.lower():
            self.orch.speak("Let me check my long-term memory...", silent=True)
            results = self.orch.brain.vector_store.search_episodes(command, limit=3)
            if results:
                context = "\n".join([r.get('text', '') for r in results])
                response = self.orch.brain.ask(f"Based on these memory chunks:\n{context}\n\nAnswer the user: '{command}'")
                self.orch.speak(response)
            else:
                self.orch.speak("I couldn't find anything related to that in my memory.")
            return

        # P0 Feature 8: Personal Assistant Mode (Daily Briefing)
        if command.lower() in ["good morning flexie", "daily briefing", "system report"]:
            self.orch.speak(f"Good morning {Config.USER_NAME}! Gathering your daily briefing...", silent=True)
            # Gather state
            notes = self.orch.brain.vector_store.search_episodes("User Note", limit=3)
            notes_text = "Recent notes:\n" + "\n".join([n.get('text', '') for n in notes]) if notes else "No recent notes."

            prompt = (
                f"Generate a very brief spoken daily briefing for {Config.USER_NAME}.\n"
                f"Include:\n{notes_text}\n"
                "System status is GREEN. Mention the time and wish them a productive day."
            )
            briefing = self.orch.brain.ask(prompt)
            self.orch.speak(briefing)
            return

        # P0 Feature 5: Voice Macros
        if command.lower() in self.macros:
            self.orch.speak(f"Executing macro: {command}")
            for step in self.macros[command.lower()]:
                self.orch.cmd_queue.put(step)
            return

        command = self._smart_followup(command)

        # Thread safety delegation guard
        curr_thread = threading.get_ident()
        if hasattr(self.orch, "_action_thread_id") and curr_thread != self.orch._action_thread_id:
            self.logger.info(f"[THREAD SAFE DELEGATION]: Queueing command '{command}' from thread {curr_thread}")
            self.orch.cmd_queue.put(command)
            return "delegated"

        # 1. Start Telemetry Trace
        trace = self.telemetry.start_trace(command)

        # 2. Safety Validation
        if not self.safety.validate(command):
            self.orch.speak("Security Alert: This command violates safety protocols and has been blocked.")
            self.telemetry.end_trace(trace, status="blocked", error="Safety violation")
            return "blocked"

        # 3. DANGER GATE & PERMISSION CHECK: high-impact actions require explicit human confirmation.
        is_dangerous = self.danger_gate.detect(command)
        perm_level = self.permission_system.classify_action(command) if self.permission_system else None
        ps = self.permission_system
        needs_level = bool(
            perm_level and ps
            and perm_level.value >= PermissionLevel.USER_CONFIRMATION.value
            and ps.current_level.value < perm_level.value
        )
        # An approval that is currently active at/above the required level already covers
        # this command (e.g. the agent executor asked the user a moment ago) — don't ask twice.
        approval_active = bool(
            perm_level and ps
            and (
                (ps.current_level.value > ps.default_level.value
                 and ps.current_level.value >= perm_level.value)
                or ps.grant_covers(perm_level)   # approved a moment ago for THIS running action
            )
        )
        requires_approval = (is_dangerous or needs_level) and not approval_active
        if requires_approval:
            self.pending_confirmation = command
            self.pending_since = time.monotonic()
            self._pending_handler_args = getattr(self, "_handler_args", ((), {}))
            self.pending_request_id = None
            if self.permission_system:
                level_to_req = perm_level or PermissionLevel.USER_CONFIRMATION
                req = self.permission_system.create_approval_request(command, level=level_to_req)
                self.pending_request_id = req.get("id")
            if hasattr(self.orch, "send_to_ui"):
                self.orch.send_to_ui("APPROVAL_REQUEST", command)
            if is_dangerous:
                self.orch.speak(
                    "That action is destructive or irreversible. Say 'confirm' to proceed, or 'cancel' to abort."
                )
            else:
                self.orch.speak(
                    "That will change something on your computer. Say 'confirm' to proceed, or 'cancel' to abort."
                )
            self.telemetry.end_trace(trace, status="awaiting_confirmation")
            return "awaiting_confirmation"

        return self._invoke(command, trace)

    def _handle_confirmation(self, command: str) -> str:
        """Resolves a pending high-impact command against the user's reply.

        Returns an execution status so callers (e.g. the blocking action worker)
        know whether the deferred command actually ran.
        """
        if self.danger_gate.is_confirmation(command):
            confirmed = self.pending_confirmation
            rid = self.pending_request_id
            self.pending_confirmation = None
            self.pending_request_id = None
            approved = True
            if self.permission_system:
                # Approve exactly the request this question was about (never "whatever is pending").
                approved = bool(rid) and self.permission_system.approve_request(rid)
            if not approved:
                self.orch.speak("That request expired, so I did not run it.")
                if hasattr(self.orch, "send_to_ui"):
                    self.orch.send_to_ui("APPROVAL_RESOLVED", "expired")
                return "cancelled"
            if hasattr(self.orch, "send_to_ui"):
                self.orch.send_to_ui("APPROVAL_RESOLVED", "approved")
            self.orch.speak("Confirmed. Executing now.", silent=True)
            # Dispatch with a fresh trace; the approval is a grant for THIS command only, active
            # only while it runs, and dropped afterwards.
            try:
                self._handler_args = getattr(self, "_pending_handler_args", ((), {}))
                if self.permission_system:
                    with self.permission_system.grant_scope(rid):
                        return self._invoke(confirmed)
                return self._invoke(confirmed)
            finally:
                if self.permission_system:
                    self.permission_system.consume_approval()
        elif self.danger_gate.is_cancellation(command):
            self._clear_pending(reject=True)
            if hasattr(self.orch, "send_to_ui"):
                self.orch.send_to_ui("APPROVAL_RESOLVED", "rejected")
            self.orch.speak("Cancelled. No action was taken.")
            return "cancelled"
        else:
            self.orch.speak("Say 'confirm' to proceed, or 'cancel' to abort.")
            return "awaiting_confirmation"

    def _invoke(self, command: str, trace: dict = None) -> str:
        """Runs the wrapped orchestrator logic and records a telemetry trace."""
        trace = trace or self.telemetry.start_trace(command)
        try:
            h_args, h_kwargs = getattr(self, "_handler_args", ((), {}))
            result = self.original_handle(command, *h_args, **h_kwargs)
            if result is False:
                self.telemetry.end_trace(trace, status="failed", error="Handler returned failure")
                return "failed"

            self.telemetry.end_trace(trace, status="success")

            context_getter = getattr(self.orch.memory, "get_conversation_messages", None)
            if callable(context_getter):
                context_list = context_getter(limit=3)
                context_str = "\n".join(
                    f"{item.get('role', 'user')}: {item.get('content', '')}"
                    for item in context_list
                )
            else:
                context_str = self.orch.memory.get_context(limit=3)
                if not isinstance(context_str, str):
                    context_str = "\n".join(str(item) for item in context_str)
            self.long_term.learn_from_history(context_str)
            return "executed"

        except Exception as e:
            self.logger.error(f"Controller Execution Error: {e}")
            self.telemetry.end_trace(trace, status="failed", error=str(e))
            self.orch.speak(f"I encountered a technical issue during execution: {e}")
            return "failed"

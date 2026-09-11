import json
import logging
import os
import threading
import time

import pyautogui

from core.danger_gate import DangerGate
from core.safety import SafetyGuard
from core.telemetry import Telemetry
from engines.long_term_memory import GlobalMemory


class FlexieController:
    """The Agentic Exoskeleton. Wraps the Orchestrator with Production layers."""
    def __init__(self, orchestrator, original_handle):
        self.orch = orchestrator
        self.original_handle = original_handle
        self.telemetry = Telemetry()
        self.safety = SafetyGuard()
        self.danger_gate = DangerGate()
        self.long_term = GlobalMemory()
        self.logger = logging.getLogger("Flexie.Controller")

        # P0 Feature 1: Continuous Conversation Mode
        self.last_command_time = time.time()
        threading.Thread(target=self._conversation_watchdog, daemon=True).start()

        # Danger Gate: command awaiting explicit user confirmation (or None)
        self.pending_confirmation = None

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
        except Exception:
            pass
        return {
            "start coding mode": ["open vscode", "open browser"],
            "research mode": ["open browser", "new tab"]
        }

    def _conversation_watchdog(self):
        while True:
            time.sleep(5)
            if self.orch.active and (time.time() - self.last_command_time > 30):
                self.orch.active = False
                # Never let a stale confirmation silently expire into an
                # unrelated future command being mistaken for "confirm".
                self.pending_confirmation = None
                if not self.dictation_active and not self.meeting_active:
                    self.logger.info("Session closed due to inactivity.")

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

    def execute(self, command: str):
        """Processes a command through the safety and telemetry pipeline."""
        self.last_command_time = time.time()

        # DANGER GATE: an earlier high-impact command awaits user confirmation.
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
                transcript = "\n".join(self.orch.memory.get_context(limit=20))
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
            self.orch.speak("Good morning Dhanush! Gathering your daily briefing...", silent=True)
            # Gather state
            notes = self.orch.brain.vector_store.search_episodes("User Note", limit=3)
            notes_text = "Recent notes:\n" + "\n".join([n.get('text', '') for n in notes]) if notes else "No recent notes."

            prompt = (
                f"Generate a very brief spoken daily briefing for Dhanush.\n"
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

        # 3. DANGER GATE: high-impact actions require explicit human confirmation.
        if self.danger_gate.detect(command):
            self.pending_confirmation = command
            self.orch.speak(
                "That action is destructive or irreversible. Say 'confirm' to proceed, or 'cancel' to abort."
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
            self.pending_confirmation = None
            self.orch.speak("Confirmed. Executing now.", silent=True)
            # Dispatch with a fresh trace; danger gate already approved.
            return self._invoke(confirmed)
        elif self.danger_gate.is_cancellation(command):
            self.pending_confirmation = None
            self.orch.speak("Cancelled. No action was taken.")
            return "cancelled"
        else:
            self.orch.speak("Say 'confirm' to proceed, or 'cancel' to abort.")
            return "awaiting_confirmation"

    def _invoke(self, command: str, trace: dict = None) -> str:
        """Runs the wrapped orchestrator logic and records a telemetry trace."""
        trace = trace or self.telemetry.start_trace(command)
        try:
            # Invoke Existing Logic (UNTOUCHED)
            self.original_handle(command)

            # End Trace
            self.telemetry.end_trace(trace, status="success")

            # Background Learning
            context_list = self.orch.memory.get_context(limit=3)
            context_str = "\n".join([str(c) for c in context_list])
            self.long_term.learn_from_history(context_str)
            return "executed"

        except Exception as e:
            self.logger.error(f"Controller Execution Error: {e}")
            self.telemetry.end_trace(trace, status="failed", error=str(e))
            self.orch.speak(f"I encountered a technical issue during execution: {e}")
            return "failed"

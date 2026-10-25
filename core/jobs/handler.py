"""Clean orchestrator handler bridge for background build jobs.

Keeps orchestrator lean by encapsulating all job command dispatching and voice/UI notifications here.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.jobs.manager import JobManager
from utils.config import Config

logger = logging.getLogger("flexie.jobs.handler")


def handle_job_intent(orch: Any, intent: str, command: str) -> bool:
    """Single entry point for orchestrator dispatch to the background job runner."""
    mgr = JobManager.get_instance()
    mgr.set_ai_context(getattr(orch, "brain", None), getattr(orch, "voice", None))

    # Register voice and UI notifier bridges if not yet attached
    if not getattr(mgr, "_orch_bridge_attached", False):
        def _job_notify(event_name: str, payload: dict):
            try:
                if event_name == "done":
                    orch.speak(f"Build complete for {payload.get('title')}. Everything is ready.")
                    orch.send_to_ui("JOB_DONE", payload)
                elif event_name == "failed":
                    orch.speak(f"Build phase {payload.get('phase')} failed. {payload.get('error')}")
                    orch.send_to_ui("JOB_FAILED", payload)
                elif event_name in ("started", "paused", "cancelled", "phase_done"):
                    orch.send_to_ui(f"JOB_{event_name.upper()}", payload)
            except Exception as e:
                logger.debug("Bridge notification error: %s", e)

        mgr.register_notifier(_job_notify)
        mgr._orch_bridge_attached = True

    c_clean = command.strip().lower()

    if intent in ("dev_build", "build_project"):
        cleaned = re.sub(
            r"^(can you please|could you please|can you|could you|please|kindly|i want you to|i need you to|help me)\s+",
            "",
            command,
            flags=re.IGNORECASE,
        ).strip()
        desc = re.sub(
            r"^(create\s+a(?:n)?\s+(?:application\s+)?(?:website\s+for|app(?:lication)?\s+for|project\s+for|web\s+app\s+for)?|create\s+a\s+project\s+for|build\s+a\s+project\s+for|start\s+a\s+new\s+project\s+for|generate\s+code\s+for|code\s+a\s+project\s+for|autonomous\s+build\s+for|create\s+a\s+project|build\s+a\s+project|start\s+a\s+new\s+project|create\s+an\s+app\s+for|build\s+an\s+app\s+for|create\s+a\s+web\s+app\s+for|build\s+a\s+web\s+app\s+for|build\s+project|create\s+project|create\s+an\s+app|build\s+an\s+app|create\s+a\s+modern|create\s+a|create\s+an|build\s+a\s+modern|build\s+a|build\s+an|develop\s+a|develop\s+an|make\s+a\s+modern|make\s+a|make\s+an|code\s+a|build\s+an\s+app)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        # Strip leading punctuation/dashes left by cleaning (e.g. em-dash, en-dash, hyphen)
        desc = re.sub(r"^[\u2013\u2014\-\u2015]+\s*", "", desc).strip()
        if not desc:
            desc = cleaned.strip()
        # Only ask clarification if the remaining description is too short (<3 meaningful words)
        meaningful = [w for w in re.findall(r"\w+", desc) if len(w) > 2]
        if len(meaningful) < 3:
            orch.speak("What kind of project should I build for you?")
            if hasattr(orch, "voice") and orch.voice:
                extra = orch.voice.listen(timeout=max(5, getattr(Config, "JOB_VOICE_CLARIFY_TIMEOUT", 20) // 2))
                if extra and len(extra.strip()) > 2:
                    desc = f"{desc} {extra}".strip() if desc else extra

        if not desc:
            orch.speak("Build request cancelled: no project description provided.")
            return True

        # Word-boundary aware title: don't cut in the middle of a word
        def _make_title(text: str, max_chars: int = 40) -> str:
            if len(text) <= max_chars:
                return text.strip()
            words = text.split()
            title = ""
            for w in words:
                candidate = (title + " " + w).strip() if title else w
                if len(candidate) > max_chars:
                    break
                title = candidate
            return title.strip() or text[:max_chars].strip()

        title = _make_title(desc)
        job = mgr.create_job(title=title, request_text=desc)
        mgr.submit_job(job)
        orch.speak(f"Started background build for {title}. Workspace initialized.")
        orch.send_to_ui("JOB_CREATED", job.to_dict())
        return True

    elif intent == "job_status":
        status_info = mgr.get_status_summary()
        orch.speak(status_info.get("message", "No active build job."))
        orch.send_to_ui("JOB_STATUS", status_info)
        return True

    elif intent in ("job_pause", "pause_build"):
        ok = mgr.pause_job()
        orch.speak("Build job paused." if ok else "No running build job to pause.")
        return True

    elif intent in ("job_resume", "resume_build", "fix_build"):
        ok = mgr.resume_job()
        orch.speak("Resuming build and retrying verification in the background." if ok else "No paused or failed build job found to resume.")
        return True

    elif intent == "job_fix":
        # The user reported an issue with the app. Pass their raw command as feedback.
        ok = mgr.debug_job(command)
        orch.speak("I've analyzed your feedback. Starting an autonomous bug-fixing pass on the project now." if ok else "I couldn't find a recent project to debug.")
        return True

    elif intent in ("job_cancel", "cancel_build"):
        ok = mgr.cancel_job()
        orch.speak("Build job cancelled." if ok else "No active build job to cancel.")
        return True

    elif intent in ("job_undo", "undo_last_phase"):
        ok, msg = mgr.undo_last_phase()
        orch.speak(msg)
        return True

    elif intent in ("job_open", "job_launch", "open_project"):
        from core.jobs.launcher import launch_job_workspace
        job = mgr.get_latest_job()
        if not job:
            orch.speak("No build project found to open. Please build one first.")
            return True
        res = launch_job_workspace(job, auto_browser=True)
        project_label = job.title or "project"
        parts = []
        if res.get("browser_opened"):
            parts.append(f"opened {project_label} in your browser")
        if res.get("vscode_opened"):
            parts.append("opened the project folder in VS Code")
        if not parts:
            import os
            os.startfile(job.workspace_path)
            parts.append(f"opened the project folder at {job.workspace_path}")
        orch.speak(f"Done — {' and '.join(parts)}.")

        if hasattr(orch, "send_to_ui"):
            orch.send_to_ui("JOB_LAUNCHED", res)
        return True

    return False

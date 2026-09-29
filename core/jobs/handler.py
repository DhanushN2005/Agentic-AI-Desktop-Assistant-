"""Clean orchestrator handler bridge for background build jobs.

Keeps orchestrator lean by encapsulating all job command dispatching and voice/UI notifications here.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from core.jobs.manager import JobManager

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
        desc = re.sub(
            r"^(create a project for|build a project for|start a new project for|generate code for|code a project for|autonomous build for|create a project|build a project|start a new project|create an app for|build an app for|create a web app for|build a web app for|build project|create project)\s*",
            "",
            command,
            flags=re.IGNORECASE,
        ).strip()
        if not desc:
            orch.speak("What kind of project should I build for you?")
            if hasattr(orch, "voice") and orch.voice:
                desc = orch.voice.listen(timeout=10)

        if not desc:
            orch.speak("Build request cancelled: no project description provided.")
            return True

        title = desc[:30].strip()
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

    elif intent in ("job_resume", "resume_build"):
        ok = mgr.resume_job()
        orch.speak("Resuming build job in the background." if ok else "No paused build job found to resume.")
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
            orch.speak("No build project found to open.")
            return True
        res = launch_job_workspace(job, auto_browser=True)
        if res.get("vscode_opened"):
            orch.speak(f"Opened project {job.title} in VS Code.")
        else:
            orch.speak(f"Opened workspace folder for {job.title}.")
        if hasattr(orch, "send_to_ui"):
            orch.send_to_ui("JOB_LAUNCHED", res)
        return True

    return False

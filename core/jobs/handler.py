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


_EDIT_VERB_BODY = (
    r"(?:update|edit|modify|improve|change|tweak|fix|"
    r"add\s+(?:a\s+)?(?:feature|button|page|section|dark\s+mode|dual\s+theme|option)|"
    r"make\s+(?:it\s+)?(?:responsive|darker|lighter|animated))\b"
)
_EDIT_VERBS = re.compile(r"\b" + _EDIT_VERB_BODY, re.IGNORECASE)
_NEW_BUILD = re.compile(
    r"\b(?:build|create|make|develop|generate|code|start)\s+(?:me\s+)?(?:a|an|another|new)\b"
    r"|\bnew\s+(?:project|app|application|website|site)\b|\bfrom\s+scratch\b",
    re.IGNORECASE,
)
_REFERS_EXISTING = re.compile(
    r"\b(?:my|the|this|that|current|existing|last|previous)\s+(?:\w+\s+)?"
    r"(?:app|application|project|website|site|page|build|code|ui|calculator|game|dashboard)\b",
    re.IGNORECASE,
)
_JOB_REF = re.compile(r"\bjob\s+#?([0-9a-f]{8})\b", re.IGNORECASE)
_POLITE = re.compile(
    r"^(?:can you please|could you please|can you|could you|please|kindly|i want you to|i need you to|help me)\s+",
    re.IGNORECASE,
)
_STARTS_WITH_EDIT = re.compile(r"^" + _EDIT_VERB_BODY, re.IGNORECASE)


def _referenced_job_id(command: str) -> str | None:
    m = _JOB_REF.search(command or "")
    return m.group(1).lower() if m else None


def is_edit_request(command: str) -> bool:
    """True only when the request clearly targets the existing project.

    A normal build request that merely contains 'update/change/improve' (for example
    "build a todo app that lets users edit items") is NOT an edit.
    """
    text = (command or "").strip()
    if not text or not _EDIT_VERBS.search(text):
        return False
    if _referenced_job_id(text):
        return True
    if _STARTS_WITH_EDIT.match(_POLITE.sub("", text)):
        return True
    return bool(_REFERS_EXISTING.search(text)) and not _NEW_BUILD.search(text)


def _job_is_live(mgr: Any, job: Any) -> bool:
    """True when a worker really owns/queues this job (not just a stale status on disk)."""
    try:
        return bool(mgr.is_job_live(job.id))
    except Exception:
        return False


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

    command = (command or "").strip()

    if intent in ("dev_build", "build_project"):
        from core.jobs.models import JobStatus

        existing = mgr.get_latest_job()
        edit_job_id = _referenced_job_id(command)
        if edit_job_id:
            referenced = mgr.get_latest_job(edit_job_id)
            if referenced:
                existing = referenced
        if existing and is_edit_request(command):
            if _job_is_live(mgr, existing):
                orch.speak(
                    f"'{existing.title}' is still being built. Say 'cancel build' to stop it, "
                    "or ask for your change again once it finishes."
                )
                return True
            ok = mgr.debug_job(command, job_id=existing.id)
            orch.speak(
                f"Updating {existing.title} — running a repair pass for your changes."
                if ok
                else "I couldn't start an update for that project right now."
            )
            return True

        # Deduplication: don't spawn a second job while one is genuinely running/queued.
        # Stale RUNNING/QUEUED rows on disk (nothing alive behind them) do not count.
        _active = existing
        if _active and _active.status in (JobStatus.RUNNING, JobStatus.QUEUED) and _job_is_live(mgr, _active):
            orch.speak(
                f"A build for '{_active.title}' is already in progress. "
                "Say 'build status' to check it or 'cancel build' to stop it first."
            )
            return True

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
        # Only ask clarification if the remaining description is too short (<2 meaningful words)
        # "wall clock", "todo app" etc. are valid 2-word descriptions — don't ask again
        meaningful = [w for w in re.findall(r"\w+", desc) if len(w) > 2]
        if len(meaningful) < 2:
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
            from core.jobs.launcher import open_folder
            opened, detail = open_folder(job.workspace_path)
            if opened:
                parts.append(f"opened the project folder at {job.workspace_path}")
            else:
                orch.speak(f"I couldn't open the project. {detail}")
                return True
        orch.speak(f"Done — {' and '.join(parts)}.")

        if hasattr(orch, "send_to_ui"):
            orch.send_to_ui("JOB_LAUNCHED", res)
        return True

    return False

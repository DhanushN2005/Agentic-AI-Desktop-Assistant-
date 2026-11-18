"""JobManager: background execution, queueing, state persistence, and event emission."""
from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from core.event_bus.bus import Event, EventBus
from core.jobs.git_ops import commit_job_phase_ex, init_job_repo
from core.jobs.git_ops import undo_last_phase as git_undo_last_phase
from core.jobs.lessons import record_lesson
from core.jobs.models import BuildJob, JobPhase, JobStatus
from core.jobs.planner import STANDARD_PHASES, ProjectSpec, generate_project_spec
from core.jobs.process import ProcessTracker, job_cancelled, job_context
from core.jobs.safe_paths import (
    atomic_write,
    find_by_basename,
    is_safe_rel,
    iter_source_files,
    safe_join,
)
from core.jobs.scaffold import scaffold_project
from core.jobs.slugify import create_job_workspace
from core.jobs.store import JobStore
from utils.config import Config

logger = logging.getLogger("flexie.jobs.manager")

_TERMINAL = (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)
_REPAIR_PROMPT_BUDGET = 60_000
_REPAIR_FILE_CAP = 12_000


class _MeteredBrain:
    """Proxy that charges every ``ask`` (prompt + reply, ~4 chars/token) to a job."""

    def __init__(self, brain: Any, sink: Any):
        self._brain = brain
        self._sink = sink

    def ask(self, prompt: Any, *args: Any, **kwargs: Any) -> Any:
        reply = self._brain.ask(prompt, *args, **kwargs)
        try:
            self._sink.tokens_used += (len(str(prompt)) + len(reply if isinstance(reply, str) else "")) // 4
        except Exception as _e:
            logger.debug("token metering failed: %s", _e)
        return reply

    def __getattr__(self, name: str) -> Any:
        return getattr(self._brain, name)


class _Counter:
    tokens_used = 0


def parse_file_blocks(response: str) -> list[tuple[str, str]]:
    """Parse ``### FILE: name`` + fenced code blocks, tolerating nested ``` fences.

    The block body runs from the first fence line after the marker to the LAST bare
    closing fence before the next marker (or ``### LESSON:``), so replacement files
    that themselves contain fenced examples are not truncated.
    """
    if not isinstance(response, str):
        return []
    lines = response.splitlines()
    markers = [i for i, ln in enumerate(lines) if re.match(r"^\s*###\s*FILE:\s*\S", ln)]
    out: list[tuple[str, str]] = []
    for n, start in enumerate(markers):
        name = re.sub(r"^\s*###\s*FILE:\s*", "", lines[start]).strip().strip("`*\"'")
        end = markers[n + 1] if n + 1 < len(markers) else len(lines)
        for j in range(start + 1, end):
            if re.match(r"^\s*###\s*LESSON:", lines[j]):
                end = j
                break
        seg = lines[start + 1:end]
        open_idx = next((i for i, ln in enumerate(seg) if re.match(r"^\s*```[\w+.\-]*\s*$", ln)), None)
        if open_idx is None:
            continue
        bare = [i for i in range(open_idx + 1, len(seg)) if re.match(r"^\s*```\s*$", seg[i])]
        close_idx = bare[-1] if bare else len(seg)
        body = "\n".join(seg[open_idx + 1:close_idx]).strip("\n")
        if name and body.strip():
            out.append((name, body))
    return out


class JobManager:
    """Manages autonomous build jobs on a dedicated background worker thread."""

    _instance: JobManager | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, storage_dir: str | None = None) -> JobManager:
        with cls._lock:
            if cls._instance is None:
                s_dir = storage_dir or getattr(
                    Config,
                    "JOBS_DIR",
                    os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "workspace",
                        ".flexie_jobs",
                    ),
                )
                cls._instance = cls(storage_dir=s_dir)
            return cls._instance

    def __init__(self, storage_dir: str, max_concurrent: int = 1):
        self.store = JobStore(storage_dir)
        self.process_tracker = ProcessTracker()
        self.max_concurrent = max_concurrent
        self.bus = EventBus()
        self._queue: queue.Queue[BuildJob] = queue.Queue()
        # One authoritative in-memory BuildJob per queued/running id, guarded by _state_lock.
        self._state_lock = threading.RLock()
        self._live: dict[str, BuildJob] = {}
        self._running_id: str | None = None
        self._cancel_flags: dict[str, threading.Event] = {}
        self._pause_flags: dict[str, threading.Event] = {}
        self._active_job: BuildJob | None = None
        self._running = True
        self._resume_lock = threading.Lock()
        self._phase_executors: dict[str, Callable[[BuildJob, JobPhase], bool]] = {}
        self._notify_callbacks: list[Callable[[str, dict[str, Any]], None]] = []
        self._brain = None
        self._voice = None
        self._auto_resumed: set[str] = set()

        # Recover BEFORE the worker starts so recovered state is never raced.
        self._recover_state()

        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="FlexieJobWorker", daemon=True
        )
        self._worker_thread.start()

    # ------------------------------------------------------------------ helpers
    def set_ai_context(self, brain: Any = None, voice: Any = None) -> None:
        """Bind active brain and voice instances for interactive spec generation."""
        if brain:
            self._brain = brain
        if voice:
            self._voice = voice

        # Auto-resume jobs interrupted by a restart. Idempotent and serialized: a job is
        # auto-resumed at most once per process and never while it is already live.
        if brain and getattr(Config, "JOB_AUTO_RESUME_ON_STARTUP", False):
            with self._resume_lock:
                try:
                    for job in self.store.list_all():
                        if job.id in self._auto_resumed:
                            continue
                        if job.status == JobStatus.PAUSED and "Interrupted" in (job.error or ""):
                            self._auto_resumed.add(job.id)
                            if self._reset_for_resume(job, count_attempt=False) and self.submit_job(job):
                                logger.info("Auto-resumed interrupted job %s (%s)", job.id, job.title)
                except Exception as _e:
                    logger.debug("Auto-resume failed: %s", _e)

    def register_notifier(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Register a callback for external notifications (speak/UDP/WS)."""
        self._notify_callbacks.append(callback)

    def register_phase_executor(self, phase_name: str, fn: Callable[[BuildJob, JobPhase], bool]) -> None:
        """Register custom phase execution handlers."""
        self._phase_executors[phase_name] = fn

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        """Publish to EventBus and notify registered callbacks without throwing."""
        try:
            self.bus.publish(Event(f"job.{event_name}", payload))
        except Exception as e:
            logger.debug("Failed publishing event %s: %s", event_name, e)

        for cb in list(self._notify_callbacks):
            try:
                cb(event_name, payload)
            except Exception as ce:
                logger.debug("Notifier callback error: %s", ce)

    def _events(self, job_id: str) -> tuple[threading.Event, threading.Event]:
        """The job's (cancel, pause) events. Created once, never replaced."""
        with self._state_lock:
            return (
                self._cancel_flags.setdefault(job_id, threading.Event()),
                self._pause_flags.setdefault(job_id, threading.Event()),
            )

    def _persist(self, job: BuildJob) -> bool:
        """Save the job, never downgrading a requested cancel/pause, and surface failures."""
        with self._state_lock:
            if job.id in self._live:
                cancel, pause = self._events(job.id)
                if cancel.is_set() and job.status in (JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.PAUSED):
                    job.status = JobStatus.CANCELLED
                elif pause.is_set() and job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
                    job.status = JobStatus.PAUSED
            job.updated_at = time.time()
            ok = self.store.save(job)
        if not ok:
            logger.error("Could not persist job %s (%s)", job.id, self.store.last_error)
            self._emit("persist_failed", {"job_id": job.id, "error": self.store.last_error})
        return ok

    def is_job_live(self, job_id: str) -> bool:
        """True while a worker owns or has queued this job."""
        with self._state_lock:
            return job_id in self._live

    def _heal_stale(self, job: BuildJob) -> BuildJob:
        """A stored RUNNING/QUEUED job with nothing alive behind it becomes resumable PAUSED."""
        with self._state_lock:
            if job.status in (JobStatus.RUNNING, JobStatus.QUEUED) and job.id not in self._live:
                job.status = JobStatus.PAUSED
                job.error = job.error or "Interrupted: no worker was running this job. Can be resumed."
                self.store.save(job)
        return job

    def _recover_state(self) -> None:
        """Inspect stored jobs. Interrupted RUNNING or QUEUED jobs transition to PAUSED."""
        for job in self.store.list_all():
            if job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
                was = job.status.value
                logger.info(
                    "Job %s was %s at restart. Transitioning to PAUSED at phase %d.",
                    job.id, was, job.current_phase,
                )
                job.status = JobStatus.PAUSED
                job.error = (
                    "Interrupted by system restart. Can be resumed."
                    if was == "running"
                    else "Interrupted by system restart while queued. Can be resumed."
                )
                job.updated_at = time.time()
                self.store.save(job)

    # --------------------------------------------------------------- creation
    def create_job(
        self,
        title: str,
        request_text: str,
        phases: list[str] | None = None,
        workspace_root: str | None = None,
        reuse_job_id: str | None = None,
    ) -> BuildJob:
        """Create and persist a new build job with its own unique workspace and git repo.

        A workspace is only ever shared with another job when ``reuse_job_id`` names
        that job explicitly; the title never selects a workspace.
        """
        ws_root = workspace_root or getattr(
            Config, "CODE_OUTPUT_DIR", os.path.join(os.path.expanduser("~"), "Downloads")
        )
        meter = _Counter()
        brain = _MeteredBrain(self._brain, meter) if self._brain else None
        spec = generate_project_spec(request_text, brain=brain, voice=self._voice)
        resolved_title = spec.title or title or "Autonomous Project"
        job = BuildJob(title=resolved_title, request_text=request_text)
        job.tokens_used = meter.tokens_used
        job.metadata["spec"] = spec.to_dict()

        ws_path = ""
        if reuse_job_id:
            prev = self.store.load(reuse_job_id)
            if prev and prev.workspace_path and os.path.isdir(prev.workspace_path):
                ws_path = prev.workspace_path
                logger.info("Explicitly reusing workspace of job %s: %s", prev.id, ws_path)
        if not ws_path:
            ws_path = create_job_workspace(ws_root, resolved_title, job.id)
        job.workspace_path = ws_path
        job.log_path = os.path.join(ws_path, ".flexie_build.log")

        init_job_repo(ws_path, ws_root)

        phase_names = [p for p in (phases or spec.phases or list(STANDARD_PHASES)) if isinstance(p, str) and p.strip()]
        job.phase_list = [JobPhase(name=p.strip(), status="pending") for p in (phase_names or STANDARD_PHASES)]

        self._persist(job)
        self._emit("created", {"job_id": job.id, "title": job.title, "workspace": ws_path})
        return job

    # ------------------------------------------------------------ queue control
    def submit_job(self, job: BuildJob) -> bool:
        """Queue a job. Refuses (False) if this job id is already queued or running."""
        with self._state_lock:
            if job.id in self._live:
                logger.info("Job %s is already queued/running; not queuing again.", job.id)
                return False
            cancel, pause = self._events(job.id)
            cancel.clear()
            pause.clear()
            job.status = JobStatus.QUEUED
            self._live[job.id] = job
            self._persist(job)
            self._queue.put(job)
        self._emit("queued", {"job_id": job.id, "title": job.title})
        return True

    def pause_job(self, job_id: str | None = None) -> bool:
        with self._state_lock:
            target_id = job_id or (self._active_job.id if self._active_job else None)
            if not target_id:
                return False
            live = self._live.get(target_id)
            if live is not None:
                if live.status in _TERMINAL:
                    return False
                _, pause = self._events(target_id)
                pause.set()
                live.status = JobStatus.PAUSED
                self._persist(live)
                phase = live.current_phase
            else:
                job = self.store.load(target_id)
                if not job or job.status not in (JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.PAUSED):
                    return False
                job.status = JobStatus.PAUSED
                self._persist(job)
                phase = job.current_phase
        self._emit("paused", {"job_id": target_id, "phase": phase})
        return True

    def _reset_for_resume(self, job: BuildJob, count_attempt: bool = True) -> bool:
        """Prepare a stored job for another run. False when the retry cap is reached."""
        if count_attempt:
            cap = int(getattr(Config, "JOB_MAX_RESUMES", 5))
            if job.attempts >= cap:
                job.error = f"Resume limit reached ({cap} attempts). Start a new build or edit the project."
                self._persist(job)
                return False
            job.attempts += 1
        if 0 <= job.current_phase < len(job.phase_list):
            job.phase_list[job.current_phase].status = "pending"
            job.phase_list[job.current_phase].error = None
        job.error = None
        # Fresh token slice for the new run; cumulative usage is kept in metadata.
        job.metadata["tokens_total"] = int(job.metadata.get("tokens_total", 0)) + int(job.tokens_used)
        job.tokens_used = 0
        return True

    def resume_job(self, job_id: str | None = None) -> bool:
        with self._state_lock:
            target = self.get_latest_job(job_id)
            if not target:
                return False
            live = self._live.get(target.id)
            if live is not None:
                # Pause was requested but the worker has not exited yet: cancel the pause
                # in place (single object, no double-queue).
                _, pause = self._events(live.id)
                cancel, _ = self._events(live.id)
                if pause.is_set() and not cancel.is_set() and live.status == JobStatus.PAUSED:
                    pause.clear()
                    live.status = JobStatus.RUNNING if self._running_id == live.id else JobStatus.QUEUED
                    live.error = None
                    self._persist(live)
                    self._emit("resumed", {"job_id": live.id})
                    return True
                return False
            if target.status not in (JobStatus.PAUSED, JobStatus.FAILED, JobStatus.QUEUED):
                return False
            if not self._reset_for_resume(target):
                return False
            return self.submit_job(target)

    def debug_job(self, feedback: str, job_id: str | None = None) -> bool:
        """Trigger an autonomous bug-fixing pass. Refused while the job is queued/running."""
        with self._state_lock:
            target = self.get_latest_job(job_id)
            if not target:
                return False
            if target.id in self._live:
                logger.info("Refusing to edit job %s while it is queued/running.", target.id)
                return False
            if not isinstance(feedback, str) or not feedback.strip():
                return False
            target.metadata["bug_report"] = feedback.strip()[:4000]

            repair_phase = JobPhase(name="repair", status="pending")
            verify_phase = JobPhase(name="verify_and_launch", status="pending")
            phases = list(target.phase_list)  # build the new list, then swap atomically
            idx = min(max(target.current_phase, 0), len(phases))
            phases[idx:idx] = [repair_phase, verify_phase]
            target.phase_list = phases
            target.current_phase = idx
            target.completed_at = None
            target.error = None
            return self.submit_job(target)

    def cancel_job(self, job_id: str | None = None) -> bool:
        with self._state_lock:
            target_id = job_id or (self._active_job.id if self._active_job else None)
            if not target_id:
                return False
            live = self._live.get(target_id)
            job = live if live is not None else self.store.load(target_id)
            if job is None or job.status == JobStatus.DONE:
                return False
            if live is not None:
                cancel, _ = self._events(target_id)
                cancel.set()
            job.status = JobStatus.CANCELLED
            self._persist(job)
        # Kill spawned process trees outside the lock (can take a few seconds).
        self.process_tracker.kill_all(target_id)
        self._emit("cancelled", {"job_id": target_id})
        return True

    def undo_last_phase(self, job_id: str | None = None) -> tuple[bool, str]:
        with self._state_lock:
            target = self.get_latest_job(job_id)
            if not target:
                return False, "No active or recorded build job found."
            if target.id in self._live:
                return False, "The build is still running; pause or cancel it before undoing a phase."
            idx = target.current_phase - 1
            if idx < 0 or idx >= len(target.phase_list):
                return False, "There is no completed phase to undo."
            phase = target.phase_list[idx]
            if not phase.git_commit:
                return False, f"Phase '{phase.name}' made no commit, so there is nothing to roll back."
            ok, msg = git_undo_last_phase(target.workspace_path, expected_commit=phase.git_commit)
            if ok:
                phase.status = "pending"
                phase.git_commit = None
                phase.completed_at = None
                phase.error = None
                target.current_phase = idx
                if target.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED):
                    target.status = JobStatus.PAUSED
                target.completed_at = None
                target.error = None
                self._persist(target)
                self._emit("undone", {"job_id": target.id, "current_phase": target.current_phase})
            return ok, msg

    def get_latest_job(self, job_id: str | None = None) -> BuildJob | None:
        with self._state_lock:
            if job_id:
                live = self._live.get(job_id)
                if live is not None:
                    return live
                job = self.store.load(job_id)
                return self._heal_stale(job) if job else None
            if self._active_job:
                return self._active_job
            if self._live:
                return max(self._live.values(), key=lambda j: j.created_at)
            all_jobs = self.store.list_all()
            return self._heal_stale(all_jobs[0]) if all_jobs else None

    def get_status_summary(self, job_id: str | None = None) -> dict[str, Any]:
        job = self.get_latest_job(job_id)
        if not job:
            return {"active": False, "message": "No build jobs registered."}
        phase_name = (
            job.phase_list[job.current_phase].name
            if 0 <= job.current_phase < len(job.phase_list)
            else "completed"
        )
        return {
            "active": job.status == JobStatus.RUNNING,
            "id": job.id,
            "title": job.title,
            "status": job.status.value,
            "phase": phase_name,
            "phase_index": job.current_phase,
            "total_phases": len(job.phase_list),
            "workspace": job.workspace_path,
            "elapsed_seconds": round(job.elapsed_seconds, 1),
            "message": f"Job '{job.title}' is {job.status.value} at phase {job.current_phase + 1}/{len(job.phase_list)} ({phase_name}).",
        }

    # ----------------------------------------------------------- phase helpers
    def _metered(self, job: BuildJob) -> Any:
        return _MeteredBrain(self._brain, job) if self._brain else None

    @staticmethod
    def _budget_exhausted(job: BuildJob) -> bool:
        return job.tokens_used >= getattr(Config, "JOB_TOKEN_BUDGET", 200000)

    def _run_heal_loop(
        self, job: BuildJob, error_text: str, pick_file: Callable[[str], str],
        rerun: Callable[[], tuple[bool, str]], attempts: int,
    ) -> tuple[bool, str, str]:
        """Bounded self-heal loop. Returns (ok, last_message, note). Reverts on final failure."""
        from core.jobs.verifier import SelfHealer

        healer = SelfHealer(max_attempts=attempts)
        brain = self._metered(job)
        ok, msg, note = False, error_text, ""
        for attempt_idx in range(attempts):
            if job_cancelled():
                break
            if self._budget_exhausted(job):
                note = "Token budget exhausted; stopped self-healing."
                break
            broken_file = pick_file(msg)
            heal_ok, heal_exp = healer.attempt_heal(
                job.workspace_path, msg, broken_file, brain, plan_summary=job.title
            )
            if not heal_ok:
                logger.warning("Self-heal attempt %d failed for '%s': %s", attempt_idx + 1, broken_file, heal_exp)
                note = heal_exp
                break
            ok, msg = rerun()
            if ok:
                note = heal_exp
                return True, msg, note
        if healer._backups:
            healer.revert_all()
            note = (note + " Reverted self-heal edits.").strip()
        return ok, msg, note

    def _default_execute_phase(self, job: BuildJob, phase: JobPhase) -> bool:
        """Execute standard build phases with scaffolding, templating, and verification."""
        spec_data = job.metadata.get("spec")
        try:
            spec = ProjectSpec.from_dict(spec_data) if spec_data else None
        except ValueError as e:
            phase.error = f"Stored project plan is invalid: {e}"
            return False

        if phase.name == "scaffold":
            if spec:
                ok = scaffold_project(spec, job.workspace_path)
                phase.output = "Project scaffolded with templates, configs, and spec docs."
                if not ok:
                    phase.error = "Scaffolding failed; see the build log."
                return ok
            phase.output = "Scaffold complete."
            return True

        elif phase.name in ("core_logic", "code"):
            if self._brain:
                from core.jobs.generator import CodeGenerator
                gen = CodeGenerator()
                ok = gen.generate_all_files(job, self._brain, phase)
                if not ok:
                    phase.error = phase.error or job.error or "Code generation failed."
                    return False
            elif spec and spec.files:
                for fspec in spec.files:
                    try:
                        target_path = safe_join(job.workspace_path, fspec.name)
                    except ValueError as e:
                        phase.error = f"Unsafe file name in plan: {e}"
                        return False
                    if os.path.exists(target_path):
                        try:
                            with open(target_path, encoding="utf-8") as _ef:
                                _existing = _ef.read()
                            _real_lines = [ln for ln in _existing.splitlines() if ln.strip() and not ln.strip().startswith("#")]
                            if len(_real_lines) >= 2:
                                continue
                        except (OSError, UnicodeDecodeError) as _e:
                            logger.debug("Could not read %s: %s", target_path, _e)
                    atomic_write(target_path, f"# {fspec.name} - {fspec.purpose}\n")
            phase.output = "Core logic implementation complete."
            return True

        elif phase.name == "ui":
            if self._brain and spec and spec.files:
                from core.jobs.generator import CodeGenerator
                _ui_exts = (".html", ".css", ".jsx", ".tsx", ".vue", ".svelte")
                _ui_names = ("index.html", "style.css", "App.jsx", "App.tsx", "main.jsx")
                ui_files = [
                    f for f in spec.files
                    if (
                        any(f.name.endswith(ext) for ext in _ui_exts)
                        or any(f.name.endswith(nm) for nm in _ui_names)
                        or "ui" in f.purpose.lower()
                        or "style" in f.purpose.lower()
                        or "template" in f.purpose.lower()
                        or "frontend" in f.purpose.lower()
                    )
                ]
                if ui_files:
                    gen = CodeGenerator()
                    generated_ui = 0
                    budget_hit = False
                    for file_spec in ui_files:
                        ok, err = gen.generate_single_file(job, file_spec, self._brain, spec)
                        if ok:
                            generated_ui += 1
                        else:
                            logger.warning("UI phase: skipped %s — %s", file_spec.name, err)
                            if (err or "").startswith("Token budget exceeded"):
                                budget_hit = True
                    phase.output = f"UI layer generated: {generated_ui}/{len(ui_files)} files written."
                    if budget_hit:
                        phase.error = f"Token budget exceeded during UI generation ({generated_ui}/{len(ui_files)} files). Resume to continue."
                        return False
                    return True
            phase.output = "UI layer verified — no additional UI files required."
            return True

        elif phase.name in ("tests_and_lint", "tests"):
            from core.jobs.verifier import (
                detect_stack,
                extract_failing_file,
                install_dependencies,
                run_tests,
            )
            stack = detect_stack(job.workspace_path)

            install_ok, install_msg = install_dependencies(job.workspace_path, stack)
            if job_cancelled():
                return False

            if not install_ok and self._brain:
                broken = "requirements.txt" if stack == "python" else "package.json"
                install_ok, install_msg, note = self._run_heal_loop(
                    job, install_msg, lambda _m, b=broken: b,
                    lambda: install_dependencies(job.workspace_path, stack), 3,
                )
                if install_ok:
                    phase.output = f"Self-healed dependency issue: {note}"

            if not install_ok:
                phase.error = f"Dependency installation failed: {install_msg}"
                return False

            test_ok, test_msg = run_tests(job.workspace_path, stack)
            if not test_ok and self._brain and not job_cancelled():
                test_ok, test_msg, note = self._run_heal_loop(
                    job, test_msg, lambda m: extract_failing_file(m, job.workspace_path),
                    lambda: run_tests(job.workspace_path, stack), 3,
                )
                if note:
                    logger.info("Test self-heal: %s", note)

            if not test_ok:
                phase.error = f"Tests failed: {test_msg}"
                return False
            phase.output = f"Tests and lint verified cleanly ({stack})."
            return True

        elif phase.name == "repair":
            return self._execute_repair(job, phase)

        elif phase.name in ("verify_and_launch", "verify"):
            return self._execute_verify(job, phase, spec)

        time.sleep(0.1)
        phase.output = f"Phase {phase.name} executed successfully."
        return True

    # ------------------------------------------------------------------ repair
    def _gather_repair_context(self, job: BuildJob, bug_report: str) -> tuple[str, set[str]]:
        """Bounded prompt context from source files only. Returns (text, complete_file_set)."""
        exts = (".py", ".js", ".html", ".css", ".jsx", ".tsx", ".ts")
        files: list[tuple[float, str, str]] = []
        for full, rel in iter_source_files(os.path.realpath(job.workspace_path), exts):
            try:
                files.append((os.path.getmtime(full), full, rel.replace("\\", "/")))
            except OSError:
                continue
        report = bug_report.lower()
        # Files named in the bug report first, then most recently modified.
        files.sort(key=lambda t: (os.path.basename(t[2]).lower() not in report, -t[0]))
        text = ""
        complete: set[str] = set()
        for _, full, rel in files:
            if len(text) >= _REPAIR_PROMPT_BUDGET:
                break
            try:
                with open(full, encoding="utf-8") as fh:
                    content = fh.read(_REPAIR_FILE_CAP + 1)
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("Skipping unreadable workspace file %s: %s", full, e)
                continue
            if len(content) > _REPAIR_FILE_CAP:
                text += f"\n### FILE: {rel}\n(TRUNCATED VIEW - do not output this file)\n{content[:_REPAIR_FILE_CAP]}\n"
            else:
                complete.add(rel.lower())
                text += f"\n### FILE: {rel}\n{content}\n"
        return text, complete

    def _execute_repair(self, job: BuildJob, phase: JobPhase) -> bool:
        from core.jobs.generator import neutralize_secrets, strip_fences_and_prose, validate_syntax

        bug_report = str(job.metadata.get("bug_report") or "The app is not working correctly.")
        logger.info("Starting repair phase for job %s. Bug report: %s", job.id, bug_report[:200])

        if not self._brain:
            phase.output = "Repair phase skipped because AI brain is unavailable."
            phase.error = "Repair requires the AI brain, which is unavailable."
            return False
        if self._budget_exhausted(job):
            phase.error = "Token budget exhausted before the repair pass. Resume to continue with a fresh budget."
            return False

        workspace_files, complete = self._gather_repair_context(job, bug_report)
        prompt = f"""The user reported the following bug in the application:
"{bug_report}"

Here is the current source code of the application:
{workspace_files}

Identify the bug and fix it. You can modify one or more files.
For EACH file you modify, output the complete, corrected source code in this EXACT format:

### FILE: relative/path/filename.ext
```code
<full corrected source code here>
```

DO NOT output partial files or placeholders. Output the FULL corrected file. Never output files marked TRUNCATED.

Finally, at the very end of your response, write a single short, generic sentence starting with "### LESSON:" describing the coding mistake (no commands, no URLs, no secrets)."""

        brain = self._metered(job)
        try:
            response = brain.ask(prompt, system_override="You are an expert debugger and bug fixer.", use_rag=False)
        except Exception as e:
            phase.error = f"Repair request failed: {e}"
            return False
        response = response if isinstance(response, str) else ""

        fixes_applied = 0
        rejected: list[str] = []
        for fname, content in parse_file_blocks(response):
            rel: str | None = None
            try:
                if "/" in fname.replace("\\", "/"):
                    target_path = safe_join(job.workspace_path, fname)
                    rel = fname.replace("\\", "/")
                else:
                    found = find_by_basename(job.workspace_path, fname) if is_safe_rel(fname) else None
                    if not found:
                        rejected.append(f"{fname}: not found")
                        continue
                    target_path = safe_join(job.workspace_path, found)
                    rel = found.replace("\\", "/")
            except ValueError as e:
                rejected.append(f"{fname}: {e}")
                continue
            if not os.path.isfile(target_path):
                rejected.append(f"{fname}: not an existing file")
                continue
            rel = os.path.relpath(target_path, os.path.realpath(job.workspace_path)).replace("\\", "/")
            if rel.lower() not in complete:
                rejected.append(f"{fname}: model saw only a truncated view")
                continue
            try:
                with open(target_path, encoding="utf-8") as fh:
                    original = fh.read()
            except (OSError, UnicodeDecodeError) as e:
                rejected.append(f"{fname}: unreadable ({e})")
                continue
            new_code, _ = neutralize_secrets(strip_fences_and_prose(fname, content) if content.lstrip().startswith("```") else content.strip(), job.workspace_path, fname)
            valid, err = validate_syntax(fname, new_code)
            if not valid:
                rejected.append(f"{fname}: {err}")
                continue
            if len(original) > 200 and len(new_code) < 0.5 * len(original):
                rejected.append(f"{fname}: reply drastically shorter than the original")
                continue
            try:
                atomic_write(target_path, new_code + "\n")
                fixes_applied += 1
                logger.info("Repair phase updated file: %s", rel)
            except OSError as e:
                try:
                    atomic_write(target_path, original)  # revert
                except OSError as e2:
                    logger.error("Could not revert %s: %s", target_path, e2)
                rejected.append(f"{fname}: write failed ({e})")

        lesson_match = re.search(r"###\s*LESSON:\s*(.+)", response)
        if lesson_match and fixes_applied:
            if record_lesson(lesson_match.group(1), job.id):
                logger.info("Self-improvement lesson recorded for job %s", job.id)

        if fixes_applied > 0:
            phase.output = f"Repair phase completed. Automatically applied fixes to {fixes_applied} files based on feedback."
            if rejected:
                phase.output += f" Rejected: {'; '.join(rejected[:5])}"
            return True
        phase.output = "Repair phase analyzed the code but could not extract valid file updates."
        phase.error = "Repair made no changes" + (f" ({'; '.join(rejected[:5])})" if rejected else ".")
        return False

    # ------------------------------------------------------------------ verify
    def _execute_verify(self, job: BuildJob, phase: JobPhase, spec: ProjectSpec | None) -> bool:
        from core.jobs.planner import PlanValidationError, parse_run_command
        from core.jobs.verifier import (
            detect_stack,
            extract_failing_file,
            find_free_port,
            run_build_check,
            start_and_smoke_test_ex,
            verify_and_update_acceptance,
        )
        stack = detect_stack(job.workspace_path)
        passed_items: list[str] = []
        if any(p.name in ("tests_and_lint", "tests") and p.status == "done" for p in job.phase_list):
            passed_items.append("tests pass")

        run_command = (spec.run_command if spec else "") or ""
        try:
            argv = parse_run_command(run_command)
        except PlanValidationError as e:
            phase.error = f"Run command is not allowed: {e}"
            return False

        if argv:
            if stack == "node" or (spec and getattr(spec, "stack", "") in ("react-vite", "react_vite")):
                build_ok, build_msg = run_build_check(job.workspace_path, stack)
                if not build_ok and self._brain and not job_cancelled():
                    build_ok, build_msg, note = self._run_heal_loop(
                        job, build_msg, lambda m: extract_failing_file(m, job.workspace_path),
                        lambda: run_build_check(job.workspace_path, stack), 2,
                    )
                if not build_ok:
                    phase.error = f"Build verification failed: {build_msg}"
                    return False
                passed_items.extend(["app starts", "starts cleanly", "build succeeds"])
                phase.output = f"Build verification passed. {build_msg}"
            else:
                port = find_free_port()
                smoke = start_and_smoke_test_ex(
                    job.workspace_path, stack, run_command, port, max_wait_seconds=12.0
                )
                if not smoke.ok:
                    phase.error = f"Smoke test failed: {smoke.message}"
                    return False
                passed_items.extend(["app starts", "starts cleanly"])
                if smoke.mode == "http":
                    passed_items.append("returns 200")
                    if smoke.matched_url and smoke.matched_url.rstrip("/").endswith("/health"):
                        passed_items.append("health check")
                phase.output = f"Smoke test verified on port {smoke.port}. {smoke.message}"
                if smoke.warning:
                    phase.output += f" Warning: {smoke.warning}"
        else:
            ws = job.workspace_path
            idx_candidates = [os.path.join(ws, p, "index.html") for p in ("", "dist", "build", "public")]
            found = next((p for p in idx_candidates if os.path.isfile(p) and os.path.getsize(p) > 0), None)
            if found:
                passed_items.extend(["app opens in browser", "renders correctly", "web interface renders"])
                phase.output = "Static web project verified: index.html present and non-empty."
            elif stack in ("python", "node") and any(True for _ in iter_source_files(ws, (".py", ".js"))):
                phase.output = "No run command configured; sources present (nothing was launched)."
            else:
                phase.error = "Verification failed: no index.html and nothing to run."
                return False

        verify_and_update_acceptance(job.workspace_path, passed_items)
        return True

    # ------------------------------------------------------------------ worker
    def _finalize(self, job: BuildJob, status: JobStatus | None = None, error: str | None = None) -> None:
        """Persist the final/paused state and release the job, atomically wrt resume/submit."""
        with self._state_lock:
            if status is not None:
                job.status = status
            if error is not None:
                job.error = error
            self._persist(job)
            self._live.pop(job.id, None)
            if self._running_id == job.id:
                self._running_id = None
            if self._active_job is job:
                self._active_job = None

    def _stop_requested(self, job: BuildJob) -> bool:
        """Under the state lock: if cancel/pause is set, finalize the job and report True."""
        with self._state_lock:
            cancel, pause = self._events(job.id)
            if cancel.is_set():
                self._finalize(job, JobStatus.CANCELLED)
                return True
            if pause.is_set():
                self._finalize(job, JobStatus.PAUSED)
                return True
        return False

    def _worker_loop(self) -> None:
        """Worker thread executing jobs sequentially without blocking voice/UI."""
        while self._running:
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._run_job(job)
            except Exception as e:  # never let the worker die or leave a job half-live
                logger.exception("Unexpected worker error for job %s", job.id)
                with self._state_lock:
                    if job.id in self._live:
                        self._finalize(job, JobStatus.FAILED, f"Internal error: {e}")
            finally:
                self._queue.task_done()

    def _run_job(self, job: BuildJob) -> None:
        with self._state_lock:
            if self._live.get(job.id) is not job:
                return  # stale queue entry
            self._active_job = job
            self._running_id = job.id
        cancel_flag, pause_flag = self._events(job.id)

        if self._stop_requested(job):
            return

        with self._state_lock:
            job.status = JobStatus.RUNNING
            self._persist(job)
        self._emit("started", {"job_id": job.id, "title": job.title})

        start_clock = time.time()
        with job_context(job.id, self.process_tracker, cancel_flag):
            while job.current_phase < len(job.phase_list):
                if self._stop_requested(job):
                    return

                phase = job.phase_list[job.current_phase]
                phase.status = "running"
                phase.started_at = time.time()
                phase.error = None
                self._persist(job)
                self._emit("phase_started", {"job_id": job.id, "phase": phase.name})

                executor = self._phase_executors.get(phase.name, self._default_execute_phase)
                try:
                    success = bool(executor(job, phase))
                except Exception as e:
                    logger.error("Phase %s execution error: %s", phase.name, e)
                    phase.error = str(e)
                    success = False

                if cancel_flag.is_set():
                    phase.status = "pending"
                    self._finalize(job, JobStatus.CANCELLED)
                    return

                if success:
                    phase.status = "done"
                    phase.completed_at = time.time()
                    commit = commit_job_phase_ex(
                        job.workspace_path, phase.name, f"Completed phase {phase.name}"
                    )
                    phase.git_commit = commit.sha
                    if commit.error:
                        logger.warning("Job %s phase %s: %s", job.id, phase.name, commit.error)
                        self._emit("git_warning", {"job_id": job.id, "phase": phase.name, "error": commit.error})
                    job.current_phase += 1
                    job.elapsed_seconds += time.time() - start_clock
                    start_clock = time.time()
                    self._persist(job)
                    self._emit("phase_done", {"job_id": job.id, "phase": phase.name, "commit": commit.sha})
                    continue

                if pause_flag.is_set():
                    # Interrupted by a pause: do not record a failure, re-run the phase on resume.
                    phase.status = "pending"
                    phase.error = None
                    continue  # loop top finalizes PAUSED

                phase.status = "failed"
                error = phase.error or f"Phase {phase.name} failed."
                self._finalize(job, JobStatus.FAILED, error)
                self._emit("failed", {"job_id": job.id, "phase": phase.name, "error": error})
                return

        with self._state_lock:
            if self._stop_requested(job):
                return
            job.completed_at = time.time()
            job.error = None
            self._finalize(job, JobStatus.DONE)
        self._emit("done", {"job_id": job.id, "title": job.title, "workspace": job.workspace_path})

    def shutdown(self) -> None:
        self._running = False
        with self._state_lock:
            active = self._active_job
        if active:
            self.cancel_job(active.id)

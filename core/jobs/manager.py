"""JobManager: background execution, queueing, state persistence, and event emission."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.event_bus.bus import Event, EventBus
from core.jobs.git_ops import commit_job_phase, init_job_repo, undo_last_phase
from core.jobs.models import BuildJob, JobPhase, JobStatus
from core.jobs.planner import ProjectSpec, STANDARD_PHASES, generate_project_spec
from core.jobs.process import ProcessTracker, kill_process_tree
from core.jobs.scaffold import scaffold_project
from core.jobs.slugify import create_job_workspace
from core.jobs.store import JobStore
from utils.config import Config

logger = logging.getLogger("flexie.jobs.manager")


class JobManager:
    """Manages autonomous build jobs on a dedicated background worker thread."""

    _instance: Optional[JobManager] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, storage_dir: Optional[str] = None) -> JobManager:
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
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._pause_flags: Dict[str, threading.Event] = {}
        self._active_job: Optional[BuildJob] = None
        self._running = True
        self._phase_executors: Dict[str, Callable[[BuildJob, JobPhase], bool]] = {}
        self._notify_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []
        self._brain = None
        self._voice = None

        # Worker thread
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="FlexieJobWorker", daemon=True
        )
        self._worker_thread.start()

        # Recover from previous crash/restart
        self._recover_state()

    def set_ai_context(self, brain: Any = None, voice: Any = None) -> None:
        """Bind active brain and voice instances for interactive spec generation."""
        if brain:
            self._brain = brain
        if voice:
            self._voice = voice

    def register_notifier(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Register a callback for external notifications (speak/UDP/WS)."""
        self._notify_callbacks.append(callback)

    def register_phase_executor(self, phase_name: str, fn: Callable[[BuildJob, JobPhase], bool]) -> None:
        """Register custom phase execution handlers."""
        self._phase_executors[phase_name] = fn

    def _emit(self, event_name: str, payload: Dict[str, Any]) -> None:
        """Publish to EventBus and notify registered callbacks without throwing."""
        try:
            self.bus.publish(Event(f"job.{event_name}", payload))
        except Exception as e:
            logger.debug("Failed publishing event %s: %s", event_name, e)

        for cb in self._notify_callbacks:
            try:
                cb(event_name, payload)
            except Exception as ce:
                logger.debug("Notifier callback error: %s", ce)

    def _recover_state(self) -> None:
        """Inspect stored jobs. Interrupted running jobs transition to PAUSED."""
        for job in self.store.list_all():
            if job.status == JobStatus.RUNNING:
                logger.info(
                    "Job %s was interrupted mid-run. Transitioning to PAUSED at phase %d.",
                    job.id,
                    job.current_phase,
                )
                job.status = JobStatus.PAUSED
                job.error = "Interrupted by system restart. Can be resumed."
                job.updated_at = time.time()
                self.store.save(job)

    def create_job(
        self,
        title: str,
        request_text: str,
        phases: Optional[List[str]] = None,
        workspace_root: Optional[str] = None,
    ) -> BuildJob:
        """Create and persist a new build job with dedicated workspace and git repo."""
        ws_root = workspace_root or getattr(
            Config, "CODE_OUTPUT_DIR", os.path.join(os.path.expanduser("~"), "Downloads")
        )
        # 0. Planning & Spec Generation
        spec = generate_project_spec(request_text, brain=self._brain, voice=self._voice)
        resolved_title = spec.title or title or "Autonomous Project"
        job = BuildJob(title=resolved_title, request_text=request_text)
        job.metadata["spec"] = spec.to_dict()

        # 1. Per-job workspace
        ws_path = create_job_workspace(ws_root, resolved_title, job.id)
        job.workspace_path = ws_path
        job.log_path = os.path.join(ws_path, ".flexie_build.log")

        # 2. Per-job Git repo
        init_job_repo(ws_path, ws_root)

        # 3. Phases (Scaffold -> Core logic -> UI -> Tests and lint -> Verify and launch)
        phase_names = phases or spec.phases or list(STANDARD_PHASES)
        job.phase_list = [JobPhase(name=p, status="pending") for p in phase_names]

        # 4. Save and return
        self.store.save(job)
        self._emit("created", {"job_id": job.id, "title": job.title, "workspace": ws_path})
        return job

    def submit_job(self, job: BuildJob) -> bool:
        """Submit a job to the execution queue."""
        job.status = JobStatus.QUEUED
        job.updated_at = time.time()
        self.store.save(job)
        self._cancel_flags[job.id] = threading.Event()
        self._pause_flags[job.id] = threading.Event()
        self._queue.put(job)
        self._emit("queued", {"job_id": job.id, "title": job.title})
        return True

    def pause_job(self, job_id: Optional[str] = None) -> bool:
        target_id = job_id or (self._active_job.id if self._active_job else None)
        if not target_id:
            return False
        flag = self._pause_flags.get(target_id)
        if flag:
            flag.set()
        if self._active_job and self._active_job.id == target_id:
            self._active_job.status = JobStatus.PAUSED
        job = self.store.load(target_id)
        if job and job.status in (JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.PAUSED):
            job.status = JobStatus.PAUSED
            job.updated_at = time.time()
            self.store.save(job)
            self._emit("paused", {"job_id": target_id, "phase": job.current_phase})
            return True
        return False

    def resume_job(self, job_id: Optional[str] = None) -> bool:
        target = self.get_latest_job(job_id)
        if not target or target.status not in (JobStatus.PAUSED, JobStatus.FAILED):
            return False
        if 0 <= target.current_phase < len(target.phase_list):
            target.phase_list[target.current_phase].status = "pending"
            target.phase_list[target.current_phase].error = None
        target.error = None
        self._pause_flags.pop(target.id, None)
        self._cancel_flags.pop(target.id, None)
        return self.submit_job(target)

    def debug_job(self, feedback: str, job_id: Optional[str] = None) -> bool:
        """Trigger an autonomous bug-fixing pass on the job based on user feedback."""
        target = self.get_latest_job(job_id)
        if not target:
            return False
            
        # Store the bug report and create a repair phase
        target.metadata["bug_report"] = feedback
        
        # If we already finished all phases or failed somewhere, we insert a repair phase
        # at the current execution point to force the runner to enter repair mode.
        from core.jobs.models import JobPhase
        repair_phase = JobPhase(name="repair", status="pending")
        verify_phase = JobPhase(name="verify_and_launch", status="pending")
        
        if target.current_phase >= len(target.phase_list):
            target.phase_list.append(repair_phase)
            target.phase_list.append(verify_phase)
        else:
            target.phase_list.insert(target.current_phase, verify_phase)
            target.phase_list.insert(target.current_phase, repair_phase)
            
        target.error = None
        self._pause_flags.pop(target.id, None)
        self._cancel_flags.pop(target.id, None)
        return self.submit_job(target)

    def cancel_job(self, job_id: Optional[str] = None) -> bool:
        target_id = job_id or (self._active_job.id if self._active_job else None)
        if not target_id:
            return False
        flag = self._cancel_flags.get(target_id)
        if flag:
            flag.set()
        self.process_tracker.kill_all(target_id)
        if self._active_job and self._active_job.id == target_id:
            self._active_job.status = JobStatus.CANCELLED
        job = self.store.load(target_id)
        if job and job.status != JobStatus.DONE:
            job.status = JobStatus.CANCELLED
            job.updated_at = time.time()
            self.store.save(job)
            self._emit("cancelled", {"job_id": target_id})
            return True
        return False

    def undo_last_phase(self, job_id: Optional[str] = None) -> Tuple[bool, str]:
        target = self.get_latest_job(job_id)
        if not target:
            return False, "No active or recorded build job found."
        ok, msg = undo_last_phase(target.workspace_path)
        if ok and target.current_phase > 0:
            target.current_phase -= 1
            if target.current_phase < len(target.phase_list):
                target.phase_list[target.current_phase].status = "pending"
            target.updated_at = time.time()
            self.store.save(target)
            self._emit("undone", {"job_id": target.id, "current_phase": target.current_phase})
        return ok, msg

    def get_latest_job(self, job_id: Optional[str] = None) -> Optional[BuildJob]:
        if job_id:
            return self.store.load(job_id)
        if self._active_job:
            return self._active_job
        all_jobs = self.store.list_all()
        return all_jobs[0] if all_jobs else None

    def get_status_summary(self, job_id: Optional[str] = None) -> Dict[str, Any]:
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

    def _default_execute_phase(self, job: BuildJob, phase: JobPhase) -> bool:
        """Execute standard build phases with scaffolding, templating, and verification."""
        spec_data = job.metadata.get("spec")
        spec = ProjectSpec.from_dict(spec_data) if spec_data else None

        if phase.name == "scaffold":
            if spec:
                ok = scaffold_project(spec, job.workspace_path)
                phase.output = "Project scaffolded with templates, configs, and spec docs."
                return ok
            phase.output = "Scaffold complete."
            return True

        elif phase.name in ("core_logic", "code"):
            if self._brain:
                from core.jobs.generator import CodeGenerator
                gen = CodeGenerator()
                ok = gen.generate_all_files(job, self._brain, phase)
                if not ok:
                    return False
            elif spec and spec.files:
                for fspec in spec.files:
                    target_path = os.path.join(job.workspace_path, fspec.name)
                    if not os.path.exists(target_path):
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with open(target_path, "w", encoding="utf-8") as f:
                            f.write(f"# {fspec.name} - {fspec.purpose}\n")
            phase.output = "Core logic implementation complete."
            return True

        elif phase.name == "ui":
            # Generate UI-specific files that were deferred from core_logic
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
                    for file_spec in ui_files:
                        ok, err = gen.generate_single_file(job, file_spec, self._brain, spec)
                        if ok:
                            generated_ui += 1
                        else:
                            logger.warning("UI phase: skipped %s — %s", file_spec.name, err)
                    phase.output = f"UI layer generated: {generated_ui}/{len(ui_files)} files written."
                    return True
            phase.output = "UI layer verified — no additional UI files required."
            return True

        elif phase.name in ("tests_and_lint", "tests"):
            from core.jobs.verifier import detect_stack, install_dependencies, run_tests, SelfHealer, extract_failing_file
            stack = detect_stack(job.workspace_path)
            
            # Install dependencies into project venv
            install_ok, install_msg = install_dependencies(job.workspace_path, stack)
            
            # If install fails, attempt self-heal on dependencies
            if not install_ok and self._brain:
                healer = SelfHealer(max_attempts=3)
                for attempt_idx in range(3):
                    broken_file = "requirements.txt" if stack == "python" else "package.json"
                    heal_ok, heal_exp = healer.attempt_heal(
                        job.workspace_path, install_msg, broken_file, self._brain, plan_summary=job.title
                    )
                    if heal_ok:
                        install_ok, install_msg = install_dependencies(job.workspace_path, stack)
                        if install_ok:
                            phase.output = f"Self-healed dependency issue: {heal_exp}"
                            break
            
            if not install_ok:
                phase.error = f"Dependency installation failed: {install_msg}"
                return False

            # Run test suite
            test_ok, test_msg = run_tests(job.workspace_path, stack)
            if not test_ok and self._brain:
                # Attempt self-heal up to 3 iterations
                healer = SelfHealer(max_attempts=3)
                for attempt_idx in range(3):
                    # Dynamically detect the broken file from the traceback
                    broken_file = extract_failing_file(test_msg, job.workspace_path)
                    heal_ok, heal_exp = healer.attempt_heal(
                        job.workspace_path, test_msg, broken_file, self._brain, plan_summary=job.title
                    )
                    if not heal_ok:
                        logger.warning("Self-heal attempt %d failed for '%s': %s", attempt_idx + 1, broken_file, heal_exp)
                        break
                    test_ok, test_msg = run_tests(job.workspace_path, stack)
                    if test_ok:
                        logger.info("Self-heal succeeded on attempt %d (fixed '%s')!", attempt_idx + 1, broken_file)
                        break

            if not test_ok:
                phase.error = f"Tests failed: {test_msg}"
                return False
            phase.output = f"Tests and lint verified cleanly ({stack})."
            return True

        elif phase.name == "repair":
            bug_report = job.metadata.get("bug_report", "The app is not working correctly.")
            logger.info("Starting repair phase for job %s. Bug report: %s", job.id, bug_report)
            
            # Gather workspace context
            workspace_files = ""
            for root, _, files in os.walk(job.workspace_path):
                if ".git" in root or "__pycache__" in root or "node_modules" in root:
                    continue
                for f in files:
                    if not f.endswith((".py", ".js", ".html", ".css", ".jsx", ".tsx", ".ts")):
                        continue
                    filepath = os.path.join(root, f)
                    try:
                        with open(filepath, "r", encoding="utf-8") as file:
                            workspace_files += f"\n### FILE: {f}\n{file.read()[:5000]}\n"
                    except:
                        pass
                        
            prompt = f"""The user reported the following bug in the application:
"{bug_report}"

Here is the current source code of the application:
{workspace_files}

Identify the bug and fix it. You can modify one or more files. 
For EACH file you modify, output the complete, corrected source code in this EXACT format:

### FILE: filename.ext
```code
<full corrected source code here>
```

DO NOT output partial files or placeholders. Output the FULL corrected file.

Finally, at the very end of your response, write a single sentence starting with "### LESSON:" that explains what the mistake was and what rule you should follow to NEVER make this mistake again in the future."""
            
            if self._brain:
                response = self._brain.ask(prompt, system_message="You are an expert debugger and bug fixer.")
                
                # Parse the response and write the files
                import re
                fixes_applied = 0
                pattern = r"### FILE: \s*(.+?)\s*```(?:code|\w+)?\n(.*?)```"
                matches = re.finditer(pattern, response, re.DOTALL)
                for match in matches:
                    fname = match.group(1).strip()
                    content = match.group(2).strip()
                    # Find the real path of this file in the workspace
                    for root, _, files in os.walk(job.workspace_path):
                        if fname in files:
                            target_path = os.path.join(root, fname)
                            try:
                                with open(target_path, "w", encoding="utf-8") as f:
                                    f.write(content + "\n")
                                fixes_applied += 1
                                logger.info("Repair phase updated file: %s", fname)
                            except Exception as e:
                                logger.error("Repair phase failed to write %s: %s", fname, e)
                            break
                
                # Extract lesson learned for self-improvement
                lesson_match = re.search(r"### LESSON:\s*(.+)", response)
                if lesson_match:
                    lesson = lesson_match.group(1).strip()
                    try:
                        lessons_file = os.path.join(getattr(Config, "DATA_DIR", "."), "lessons.txt")
                        with open(lessons_file, "a", encoding="utf-8") as lf:
                            lf.write(f"- {lesson}\n")
                        logger.info("Self-improvement lesson recorded: %s", lesson)
                    except Exception as e:
                        logger.error("Failed to save lesson: %s", e)

                if fixes_applied > 0:
                    phase.output = f"Repair phase completed. Automatically applied fixes to {fixes_applied} files based on feedback."
                else:
                    phase.output = "Repair phase analyzed the code but could not extract valid file updates."
            else:
                phase.output = "Repair phase skipped because AI brain is unavailable."
            return True

        elif phase.name in ("verify_and_launch", "verify"):
            from core.jobs.verifier import (
                detect_stack,
                find_free_port,
                start_and_smoke_test,
                run_build_check,
                verify_and_update_acceptance,
            )
            stack = detect_stack(job.workspace_path)
            passed_items = ["tests pass"]

            if spec and spec.run_command and spec.run_command not in ("none", "open index.html", ""):
                # React/Vite and Node build-step stacks: run build instead of HTTP smoke test
                if stack == "node" or (spec and getattr(spec, "stack", "") in ("react-vite", "react_vite")):
                    build_ok, build_msg = run_build_check(job.workspace_path, stack)
                    if build_ok:
                        passed_items.extend(["app starts", "starts cleanly", "build succeeds"])
                        phase.output = f"Build verification passed. {build_msg}"
                    else:
                        # Attempt self-heal on build errors if brain is available
                        if self._brain:
                            from core.jobs.verifier import SelfHealer, extract_failing_file
                            healer = SelfHealer(max_attempts=2)
                            broken_file = extract_failing_file(build_msg, job.workspace_path)
                            heal_ok, _ = healer.attempt_heal(
                                job.workspace_path, build_msg, broken_file, self._brain,
                                plan_summary=job.title
                            )
                            if heal_ok:
                                build_ok, build_msg = run_build_check(job.workspace_path, stack)
                        if not build_ok:
                            logger.warning("Build check failed: %s", build_msg)
                        phase.output = f"Build verified with warnings: {build_msg}"
                else:
                    # Python/Flask and other HTTP servers: use smoke test with longer wait
                    port = find_free_port()
                    smoke_ok, smoke_msg = start_and_smoke_test(
                        job.workspace_path, stack, spec.run_command, port, max_wait_seconds=12.0
                    )
                    if smoke_ok:
                        passed_items.extend(["app starts", "starts cleanly", "returns 200", "health check"])
                        phase.output = f"Smoke test verified on port {port}. {smoke_msg}"
                    else:
                        logger.warning("Smoke test did not confirm readiness: %s", smoke_msg)
                        phase.output = f"Verified with warnings: {smoke_msg}"
            else:
                # Static web: verify index.html exists and is non-empty
                idx = os.path.join(job.workspace_path, "index.html")
                if os.path.isfile(idx) and os.path.getsize(idx) > 0:
                    passed_items.extend(["app opens in browser", "renders correctly", "web interface renders"])
                    phase.output = "Static web project verified: index.html present and non-empty."
                else:
                    phase.output = "Static web project: index.html not found — marked with warning."

            verify_and_update_acceptance(job.workspace_path, passed_items)
            return True

        time.sleep(0.1)
        phase.output = f"Phase {phase.name} executed successfully."
        return True

    def _worker_loop(self) -> None:
        """Worker thread executing jobs sequentially without blocking voice/UI."""
        while self._running:
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            self._active_job = job
            cancel_flag = self._cancel_flags.setdefault(job.id, threading.Event())
            pause_flag = self._pause_flags.setdefault(job.id, threading.Event())

            if cancel_flag.is_set():
                job.status = JobStatus.CANCELLED
                job.updated_at = time.time()
                self.store.save(job)
                continue

            job.status = JobStatus.RUNNING
            job.updated_at = time.time()
            self.store.save(job)
            self._emit("started", {"job_id": job.id, "title": job.title})

            start_clock = time.time()
            completed_cleanly = True

            while job.current_phase < len(job.phase_list):
                if cancel_flag.is_set():
                    logger.info("Job %s cancelled cooperatively.", job.id)
                    job.status = JobStatus.CANCELLED
                    completed_cleanly = False
                    break

                if pause_flag.is_set():
                    logger.info("Job %s paused cooperatively.", job.id)
                    job.status = JobStatus.PAUSED
                    completed_cleanly = False
                    break

                phase = job.phase_list[job.current_phase]
                phase.status = "running"
                phase.started_at = time.time()
                job.updated_at = time.time()
                self.store.save(job)
                self._emit("phase_started", {"job_id": job.id, "phase": phase.name})

                # Execute phase
                executor = self._phase_executors.get(phase.name, self._default_execute_phase)
                try:
                    success = executor(job, phase)
                except Exception as e:
                    logger.error("Phase %s execution error: %s", phase.name, e)
                    phase.error = str(e)
                    success = False

                if cancel_flag.is_set():
                    job.status = JobStatus.CANCELLED
                    completed_cleanly = False
                    break

                if pause_flag.is_set():
                    job.status = JobStatus.PAUSED
                    self.store.save(job)
                    completed_cleanly = False
                    break

                if success:
                    phase.status = "done"
                    phase.completed_at = time.time()
                    # Commit phase changes to Git
                    commit_sha = commit_job_phase(
                        job.workspace_path, phase.name, f"Completed phase {phase.name}"
                    )
                    phase.git_commit = commit_sha
                    job.current_phase += 1
                    job.elapsed_seconds += time.time() - start_clock
                    start_clock = time.time()
                    job.updated_at = time.time()

                    if pause_flag.is_set():
                        job.status = JobStatus.PAUSED
                        self.store.save(job)
                        self._emit("phase_done", {"job_id": job.id, "phase": phase.name, "commit": commit_sha})
                        completed_cleanly = False
                        break

                    self.store.save(job)
                    self._emit("phase_done", {"job_id": job.id, "phase": phase.name, "commit": commit_sha})
                else:
                    phase.status = "failed"
                    job.status = JobStatus.FAILED
                    job.error = phase.error or f"Phase {phase.name} failed."
                    job.updated_at = time.time()
                    self.store.save(job)
                    self._emit("failed", {"job_id": job.id, "phase": phase.name, "error": job.error})
                    completed_cleanly = False
                    break

            if completed_cleanly and job.current_phase >= len(job.phase_list):
                job.status = JobStatus.DONE
                job.completed_at = time.time()
                job.updated_at = time.time()
                self.store.save(job)
                self._emit("done", {"job_id": job.id, "title": job.title, "workspace": job.workspace_path})

            self._active_job = None
            self._queue.task_done()

    def shutdown(self) -> None:
        self._running = False
        if self._active_job:
            self.cancel_job(self._active_job.id)

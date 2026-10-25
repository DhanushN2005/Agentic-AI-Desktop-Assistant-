"""Unit and integration tests for Phase 1: Background Build Job Runner."""
import os
import shutil
import subprocess
import time
from unittest.mock import MagicMock, patch
import pytest

from core.jobs.git_ops import commit_job_phase, init_job_repo, is_git_available, undo_last_phase
from core.jobs.handler import handle_job_intent
from core.jobs.manager import JobManager
from core.jobs.models import BuildJob, JobPhase, JobStatus
from core.jobs.process import ProcessTracker, kill_process_tree
from core.jobs.slugify import create_job_workspace, slugify_job_name
from core.jobs.store import JobStore
from core.router import IntentRouter


class TestSlugifyAndWorkspace:
    def test_slugify_standard(self):
        assert slugify_job_name("Calculator App") == "calculator-app"
        assert slugify_job_name("React + Vite Dashboard v1.0") == "react-vite-dashboard-v1-0"

    def test_slugify_unicode(self):
        # Accents / umlauts stripped to ASCII
        assert slugify_job_name("Café Über Project") == "cafe-uber-project"

    def test_slugify_windows_reserved(self):
        # con, nul, aux, com1, lpt1
        assert slugify_job_name("con").startswith("p-")
        assert slugify_job_name("NUL").startswith("p-")
        assert slugify_job_name("aux-tools").startswith("p-")

    def test_slugify_length_limit(self):
        long_title = "a" * 100
        slug = slugify_job_name(long_title, max_chars=40)
        assert len(slug) <= 40

    def test_create_workspace_collision_suffix(self, tmp_path):
        ws1 = create_job_workspace(str(tmp_path), "My Tool", "abc12345")
        assert os.path.exists(ws1)
        assert "my-tool-abc12345" in os.path.basename(ws1)

        # Same title & id -> suffix appended
        ws2 = create_job_workspace(str(tmp_path), "My Tool", "abc12345")
        assert os.path.exists(ws2)
        assert os.path.basename(ws2).endswith("-2")
        assert ws1 != ws2


class TestJobModels:
    def test_job_serialization_roundtrip(self):
        phases = [JobPhase(name="plan"), JobPhase(name="code")]
        job = BuildJob(
            title="Demo Job",
            request_text="create a web server",
            phase_list=phases,
            status=JobStatus.RUNNING,
        )
        data = job.to_dict()
        assert data["title"] == "Demo Job"
        assert data["status"] == "running"
        assert len(data["phase_list"]) == 2

        restored = BuildJob.from_dict(data)
        assert restored.id == job.id
        assert restored.title == "Demo Job"
        assert restored.status == JobStatus.RUNNING
        assert len(restored.phase_list) == 2
        assert restored.phase_list[0].name == "plan"


class TestJobStore:
    def test_atomic_save_and_load(self, tmp_path):
        store = JobStore(str(tmp_path / "jobs"))
        job = BuildJob(title="Atomic Test")
        assert store.save(job) is True

        loaded = store.load(job.id)
        assert loaded is not None
        assert loaded.title == "Atomic Test"

    def test_list_all_and_delete(self, tmp_path):
        store = JobStore(str(tmp_path / "jobs"))
        j1 = BuildJob(title="Job 1")
        j2 = BuildJob(title="Job 2")
        store.save(j1)
        store.save(j2)

        jobs = store.list_all()
        assert len(jobs) == 2

        store.delete(j1.id)
        assert store.load(j1.id) is None
        assert len(store.list_all()) == 1


class TestProcessManagement:
    def test_kill_process_tree_noop_invalid_pid(self):
        assert kill_process_tree(0) is False
        assert kill_process_tree(-1) is False

    def test_process_tracker(self):
        tracker = ProcessTracker()
        proc = subprocess.Popen(["python", "-c", "import time; time.sleep(5)"])
        try:
            tracker.register("job_1", proc)
            tracker.kill_all("job_1")
            proc.wait(timeout=3)
            assert proc.poll() is not None
        finally:
            if proc.poll() is None:
                proc.kill()


class TestGitOperations:
    def test_git_init_commit_undo(self, tmp_path):
        if not is_git_available():
            pytest.skip("Git CLI not available")

        ws = tmp_path / "repo"
        ws.mkdir()
        assert init_job_repo(str(ws)) is True
        assert (ws / ".git").exists()

        # Phase 1: create file and commit
        f1 = ws / "file1.txt"
        f1.write_text("v1", encoding="utf-8")
        sha1 = commit_job_phase(str(ws), "phase1", "created file 1")
        assert sha1 is not None

        # Phase 2: modify file and commit
        f1.write_text("v2", encoding="utf-8")
        sha2 = commit_job_phase(str(ws), "phase2", "updated file 1")
        assert sha2 is not None
        assert f1.read_text(encoding="utf-8") == "v2"

        # Undo phase 2 -> should revert back to v1
        ok, msg = undo_last_phase(str(ws))
        assert ok is True
        assert f1.read_text(encoding="utf-8") == "v1"


class TestJobManagerLifecycle:
    def test_create_and_run_job_lifecycle(self, tmp_path):
        storage_dir = str(tmp_path / "jobs_store")
        ws_root = str(tmp_path / "workspaces")
        mgr = JobManager(storage_dir=storage_dir)

        # Register custom fast phase executor
        def _fast_executor(job, phase):
            # Write a marker file in workspace
            with open(os.path.join(job.workspace_path, f"{phase.name}.txt"), "w") as f:
                f.write(f"done {phase.name}")
            return True

        mgr.register_phase_executor("plan", _fast_executor)
        mgr.register_phase_executor("code", _fast_executor)

        job = mgr.create_job(
            title="Fast Test",
            request_text="Build fast test",
            phases=["plan", "code"],
            workspace_root=ws_root,
        )
        assert job.status == JobStatus.QUEUED
        assert os.path.exists(job.workspace_path)

        mgr.submit_job(job)

        # Wait for worker thread to process
        for _ in range(50):
            time.sleep(0.1)
            updated = mgr.store.load(job.id)
            if updated and updated.status in (JobStatus.DONE, JobStatus.FAILED):
                break

        final_job = mgr.store.load(job.id)
        assert final_job is not None
        assert final_job.status == JobStatus.DONE
        assert final_job.current_phase == 2
        assert os.path.exists(os.path.join(final_job.workspace_path, "plan.txt"))
        assert os.path.exists(os.path.join(final_job.workspace_path, "code.txt"))

        mgr.shutdown()

    def test_pause_and_resume_job(self, tmp_path):
        storage_dir = str(tmp_path / "jobs_store")
        mgr = JobManager(storage_dir=storage_dir)
        job = mgr.create_job("Pause Test", "req", phases=["p1", "p2"])
        mgr.submit_job(job)

        assert mgr.pause_job(job.id) is True
        paused = mgr.store.load(job.id)
        assert paused.status == JobStatus.PAUSED

        assert mgr.resume_job(job.id) is True
        resumed = mgr.store.load(job.id)
        assert resumed.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        mgr.shutdown()

    def test_cancel_job(self, tmp_path):
        storage_dir = str(tmp_path / "jobs_store")
        mgr = JobManager(storage_dir=storage_dir)
        job = mgr.create_job("Cancel Test", "req", phases=["p1"])
        mgr.submit_job(job)

        assert mgr.cancel_job(job.id) is True
        cancelled = mgr.store.load(job.id)
        assert cancelled.status == JobStatus.CANCELLED
        mgr.shutdown()

    def test_crash_recovery_transitions_running_to_paused(self, tmp_path):
        storage_dir = str(tmp_path / "jobs_store")
        store = JobStore(storage_dir)
        interrupted = BuildJob(title="Crashed Job", status=JobStatus.RUNNING)
        store.save(interrupted)

        # Starting a new manager should recover and mark as PAUSED
        mgr = JobManager(storage_dir=storage_dir)
        recovered = mgr.store.load(interrupted.id)
        assert recovered is not None
        assert recovered.status == JobStatus.PAUSED
        assert "Interrupted" in (recovered.error or "")
        mgr.shutdown()


class TestOrchestratorJobIntegration:
    def test_router_detects_job_intents(self):
        router = IntentRouter()
        assert router.route("build status")[0] == "job_status"
        assert router.route("pause the build")[0] == "job_pause"
        assert router.route("resume build")[0] == "job_resume"
        assert router.route("cancel the build")[0] == "job_cancel"
        assert router.route("undo last phase")[0] == "job_undo"

    def test_handle_job_intent_dispatch(self, tmp_path):
        mock_orch = MagicMock()
        mock_orch.speak = MagicMock()
        mock_orch.send_to_ui = MagicMock()

        with patch.object(JobManager, "get_instance") as mock_get_inst:
            mock_mgr = MagicMock()
            mock_job = BuildJob(title="My Project", workspace_path=str(tmp_path))
            mock_mgr.create_job.return_value = mock_job
            mock_mgr.get_status_summary.return_value = {"message": "Job is running"}
            mock_mgr.pause_job.return_value = True
            mock_mgr.resume_job.return_value = True
            mock_mgr.cancel_job.return_value = True
            mock_mgr.undo_last_phase.return_value = (True, "Rolled back.")
            mock_get_inst.return_value = mock_mgr

            # Test build_project
            assert handle_job_intent(mock_orch, "build_project", "build a project for todo app") is True
            mock_mgr.create_job.assert_called_once()
            mock_mgr.submit_job.assert_called_once()
            mock_orch.speak.assert_called()

            # Test job_status
            assert handle_job_intent(mock_orch, "job_status", "build status") is True
            mock_orch.speak.assert_called_with("Job is running")

            # Test job_pause
            assert handle_job_intent(mock_orch, "job_pause", "pause build") is True
            mock_mgr.pause_job.assert_called_once()

            # Test job_resume
            assert handle_job_intent(mock_orch, "job_resume", "resume build") is True
            mock_mgr.resume_job.assert_called_once()

            # Test job_cancel
            assert handle_job_intent(mock_orch, "job_cancel", "cancel build") is True
            mock_mgr.cancel_job.assert_called_once()

            # Test job_undo
            assert handle_job_intent(mock_orch, "job_undo", "undo last phase") is True
            mock_mgr.undo_last_phase.assert_called_once()

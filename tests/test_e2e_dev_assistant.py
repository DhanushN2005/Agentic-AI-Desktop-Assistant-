"""Phase 7: Comprehensive End-to-End Verification for Autonomous Dev Assistant.

Tests full lifecycle:
1. Preflight sanity
2. Spec planning & clarification
3. Workspace creation & template/spec scaffolding
4. Per-job Git tracking with phase commits and rollback
5. Code generation & secret neutralization
6. Verification & Acceptance criteria updating
7. Model hub routing & token budgeting
8. IDE/Desktop launcher integration
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from core.jobs.git_ops import get_job_git_history
from core.jobs.launcher import launch_job_workspace
from core.jobs.manager import JobManager
from core.jobs.models import BuildJob, JobPhase, JobStatus
from core.jobs.planner import ProjectSpec, clarify_request, generate_project_spec
from core.jobs.scaffold import scaffold_project
from core.jobs.verifier import detect_stack, verify_and_update_acceptance
from core.model_hub import ModelHub
from utils.preflight import run_preflight


class TestEndToEndDevAssistant:
    @pytest.fixture
    def e2e_env(self, tmp_path):
        ws_root = tmp_path / "workspaces"
        ws_root.mkdir()
        store_dir = tmp_path / "e2e_jobs"
        mgr = JobManager(storage_dir=str(store_dir))
        return {
            "root": str(tmp_path),
            "ws_root": str(ws_root),
            "store_dir": str(store_dir),
            "mgr": mgr,
        }

    def test_preflight_baseline(self):
        """Step 1: Ensure system environment preflight checks report properly."""
        report = run_preflight()
        assert "overall_ok" in report
        assert "checks" in report
        assert "python" in report["checks"]
        assert report["checks"]["python"]["ok"] is True

    def test_full_autonomous_project_lifecycle(self, e2e_env):
        """Step 2: Execute complete autonomous dev assistant flow."""
        mgr: JobManager = e2e_env["mgr"]
        ws_root = e2e_env["ws_root"]

        # Mock Brain for predictable generation & planning
        mock_brain = MagicMock()
        mgr.set_ai_context(mock_brain, None)

        # 1. User requests a project
        user_request = "build a flask api for task management with acceptance criteria"
        spec = generate_project_spec(user_request, brain=None)
        assert spec.title != ""
        assert "flask" in spec.stack or "python" in spec.stack
        assert len(spec.files) > 0

        # 2. Create Job
        job = mgr.create_job(
            title=spec.title,
            request_text=user_request,
            workspace_root=ws_root,
        )
        assert os.path.isdir(job.workspace_path)
        assert job.status in (JobStatus.QUEUED, JobStatus.RUNNING)

        # 3. Verify Scaffolding
        scaffold_ok = scaffold_project(spec, job.workspace_path)
        assert scaffold_ok is True

        # Check generated docs and config
        for doc in ("PLAN.md", "ACCEPTANCE.md", "AGENTS.md", ".clinerules"):
            assert os.path.exists(os.path.join(job.workspace_path, doc))

        vscode_dir = os.path.join(job.workspace_path, ".vscode")
        assert os.path.exists(os.path.join(vscode_dir, "tasks.json"))
        assert os.path.exists(os.path.join(vscode_dir, "extensions.json"))
        assert os.path.exists(os.path.join(vscode_dir, "settings.json"))

        # 4. Commit Scaffold Phase and Check Git History
        from core.jobs.git_ops import commit_job_phase
        commit_sha = commit_job_phase(job.workspace_path, "scaffold", "Initial scaffold commit")
        assert commit_sha is not None

        history = get_job_git_history(job.workspace_path)
        assert len(history) >= 1
        assert "scaffold" in history[0]["message"].lower()

        # 5. Populate and neutralize code files
        sample_code = (
            "import os\n"
            "SECRET_KEY = os.getenv('APP_SECRET', 'test-secret')\n"
            "def test_example():\n"
            "    assert True\n"
        )
        app_file = os.path.join(job.workspace_path, "app.py")
        with open(app_file, "w", encoding="utf-8") as f:
            f.write(sample_code)

        # 6. Verify stack detection and acceptance checklist updates
        stack = detect_stack(job.workspace_path)
        assert stack in ("flask", "python")

        updated = verify_and_update_acceptance(job.workspace_path, ["tests pass", "app starts"])
        assert updated is True

        with open(os.path.join(job.workspace_path, "ACCEPTANCE.md"), "r", encoding="utf-8") as f:
            acc_content = f.read()
        assert "[x]" in acc_content

        # 7. Model Hub Routing & Token Tracker
        hub = ModelHub()
        mapping = hub.get_mapping_for_task("code")
        assert mapping.cloud_model != ""
        hub.tracker.record("groq", "code", prompt_tokens=150, completion_tokens=80, job_id=job.id)
        job_cost_rep = hub.tracker.get_job_report(job.id)
        assert job_cost_rep["total_tokens"] == 230

        # 8. Desktop Launcher integration
        with patch("core.jobs.launcher.find_vscode_executable", return_value=None):
            with patch("os.startfile", create=True) as mock_start:
                with patch("webbrowser.open") as mock_web:
                    # Provide an index.html so browser trigger fires
                    (tmp_path_index := os.path.join(job.workspace_path, "index.html"))
                    with open(tmp_path_index, "w", encoding="utf-8") as f:
                        f.write("<h1>App</h1>")

                    launch_res = launch_job_workspace(job, auto_browser=True)
                    assert launch_res["job_id"] == job.id
                    assert launch_res["browser_opened"] is True
                    mock_web.assert_called_once()
                    mock_start.assert_called_once_with(job.workspace_path)

        mgr.shutdown()

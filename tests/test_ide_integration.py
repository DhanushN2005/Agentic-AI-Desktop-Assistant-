"""Unit tests for Phase 6: Desktop & IDE Integration."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from core.jobs.handler import handle_job_intent
from core.jobs.launcher import (
    find_browser_target,
    find_vscode_executable,
    launch_in_vscode,
    launch_job_workspace,
    open_in_browser,
)
from core.jobs.models import BuildJob
from core.jobs.planner import ProjectSpec
from core.jobs.scaffold import scaffold_project
from core.router import IntentRouter


class TestScaffoldIDE:
    def test_scaffold_creates_vscode_and_clinerules(self, tmp_path):
        ws = str(tmp_path / "test_proj")
        spec = ProjectSpec(
            title="My Python Web App",
            summary="A simple test app",
            stack="python",
            run_command="python app.py",
            test_command="pytest",
            template_used="builtin_fallback",
        )
        ok = scaffold_project(spec, ws)
        assert ok is True

        # Check .vscode/tasks.json
        tasks_path = os.path.join(ws, ".vscode", "tasks.json")
        assert os.path.exists(tasks_path)
        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks = json.load(f)
        assert tasks["version"] == "2.0.0"
        assert len(tasks["tasks"]) >= 1

        # Check .vscode/extensions.json
        ext_path = os.path.join(ws, ".vscode", "extensions.json")
        assert os.path.exists(ext_path)
        with open(ext_path, "r", encoding="utf-8") as f:
            ext = json.load(f)
        recs = ext["recommendations"]
        assert "saoudrizwan.claude-dev" in recs
        assert "rooveterinaryinc.roo-cline" in recs
        assert "ms-python.python" in recs

        # Check .vscode/settings.json
        settings_path = os.path.join(ws, ".vscode", "settings.json")
        assert os.path.exists(settings_path)
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        assert "cline.apiProvider" in settings
        assert "roo-cline.apiProvider" in settings
        assert "files.exclude" in settings

        # Check .clinerules
        clinerules_path = os.path.join(ws, ".clinerules")
        assert os.path.exists(clinerules_path)
        with open(clinerules_path, "r", encoding="utf-8") as f:
            clinerules = f.read()
        assert "PLAN.md" in clinerules
        assert "ACCEPTANCE.md" in clinerules


class TestLauncher:
    def test_find_vscode_executable(self):
        with patch("shutil.which", return_value=r"C:\Tools\code.cmd"):
            assert find_vscode_executable() == r"C:\Tools\code.cmd"

    def test_launch_in_vscode_cmd_wrapper(self, tmp_path):
        ws = str(tmp_path)
        with patch("core.jobs.launcher.find_vscode_executable", return_value=r"C:\bin\code.cmd"):
            with patch("subprocess.Popen") as mock_popen:
                res = launch_in_vscode(ws)
                assert res is True
                mock_popen.assert_called_once()
                args, kwargs = mock_popen.call_args
                cmd = args[0]
                assert cmd[0] == "cmd.exe"
                assert cmd[1] == "/c"
                assert cmd[2] == r"C:\bin\code.cmd"
                assert cmd[3] == ws
                assert kwargs["shell"] is False

    def test_launch_in_vscode_fallback_startfile(self, tmp_path):
        ws = str(tmp_path)
        with patch("core.jobs.launcher.find_vscode_executable", return_value=None):
            with patch("os.startfile", create=True) as mock_startfile:
                res = launch_in_vscode(ws)
                assert res is True
                mock_startfile.assert_called_once_with(ws)

    def test_open_in_browser(self, tmp_path):
        html_file = tmp_path / "index.html"
        html_file.write_text("<h1>Hello</h1>", encoding="utf-8")

        with patch("webbrowser.open") as mock_open:
            res = open_in_browser(str(html_file))
            assert res is True
            mock_open.assert_called_once()
            called_url = mock_open.call_args[0][0]
            assert called_url.startswith("file:///")
            assert "index.html" in called_url

    def test_find_browser_target(self, tmp_path):
        ws = str(tmp_path)
        # 1. Dev server url priority
        assert find_browser_target(ws, {"dev_server_url": "http://127.0.0.1:3000"}) == "http://127.0.0.1:3000"

        # 2. Static index.html in root
        index_file = tmp_path / "index.html"
        index_file.write_text("<html></html>", encoding="utf-8")
        assert find_browser_target(ws) == str(index_file)

    def test_launch_job_workspace(self, tmp_path):
        ws = str(tmp_path)
        (tmp_path / "index.html").write_text("<h1>App</h1>", encoding="utf-8")
        job = BuildJob(title="Demo App", workspace_path=ws)

        with patch("core.jobs.launcher.launch_in_vscode", return_value=True) as mock_vs:
            with patch("core.jobs.launcher.open_in_browser", return_value=True) as mock_br:
                report = launch_job_workspace(job, auto_browser=True)
                assert report["vscode_opened"] is True
                assert report["browser_opened"] is True
                assert report["browser_target"] == str(tmp_path / "index.html")
                mock_vs.assert_called_once_with(ws)
                mock_br.assert_called_once()


class TestHandlerAndRouterIntegration:
    def test_handle_job_open_dispatch(self, tmp_path):
        ws = str(tmp_path)
        job = BuildJob(title="My Project", workspace_path=ws)

        mock_orch = MagicMock()
        mock_orch.speak = MagicMock()
        mock_orch.send_to_ui = MagicMock()

        with patch("core.jobs.manager.JobManager.get_latest_job", return_value=job):
            with patch("core.jobs.launcher.launch_job_workspace") as mock_launch:
                mock_launch.return_value = {
                    "job_id": job.id,
                    "vscode_opened": True,
                    "browser_opened": False,
                }
                res = handle_job_intent(mock_orch, "job_open", "open project in vscode")
                assert res is True
                mock_orch.speak.assert_called_once()
                assert "opened the project folder" in mock_orch.speak.call_args[0][0].lower()
                mock_orch.send_to_ui.assert_called_with("JOB_LAUNCHED", mock_launch.return_value)

    def test_router_natural_language_job_routes(self):
        router = IntentRouter()

        # build_project
        intent, conf = router.route("build a project for task manager")
        assert intent in ("build_project", "dev_build")
        assert conf >= 0.9

        # job_status
        intent, conf = router.route("what is the build status")
        assert intent == "job_status"
        assert conf >= 0.9

        # job_pause
        intent, conf = router.route("pause the build")
        assert intent == "job_pause"
        assert conf >= 0.9

        # job_resume
        intent, conf = router.route("resume the build")
        assert intent == "job_resume"
        assert conf >= 0.9

        # job_cancel
        intent, conf = router.route("cancel the build")
        assert intent == "job_cancel"
        assert conf >= 0.9

        # job_undo
        intent, conf = router.route("undo last phase")
        assert intent == "job_undo"
        assert conf >= 0.9

        # job_open
        intent, conf = router.route("open project in vscode")
        assert intent == "job_open"
        assert conf >= 0.9

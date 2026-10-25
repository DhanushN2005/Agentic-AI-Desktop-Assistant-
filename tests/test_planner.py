"""Unit and integration tests for Phase 2: Planning, Clarification, and Scaffolding."""
import json
import os
import time
from unittest.mock import MagicMock, patch
import pytest

from core.jobs.manager import JobManager
from core.jobs.models import BuildJob, JobStatus
from core.jobs.planner import (
    ProjectFileSpec,
    ProjectSpec,
    _strip_markdown_fences,
    clarify_request,
    generate_project_spec,
    get_builtin_fallback_spec,
    is_vague_request,
    match_template,
    write_project_spec_files,
)
from core.jobs.scaffold import scaffold_project


class TestClarificationAndVagueness:
    def test_vague_requests_detected(self):
        assert is_vague_request("build a project") is True
        assert is_vague_request("create an app") is True
        assert is_vague_request("make something cool") is True
        assert is_vague_request("start new project") is True

    def test_clear_requests_not_vague(self):
        assert is_vague_request("build a python flask rest api for todos") is False
        assert is_vague_request("create a react vite dashboard with charts") is False
        assert is_vague_request("command line cli tool to format json") is False
        assert is_vague_request("calculator app with responsive html and css") is False

    def test_clarify_with_defaults_when_no_voice(self):
        refined, assumptions = clarify_request("build a project", voice=None)
        assert len(assumptions) >= 2
        assert "Assumed" in assumptions[0]
        assert "flask" in refined.lower() or "python" in refined.lower()

    def test_clarify_with_voice_responses(self):
        mock_voice = MagicMock()
        mock_voice.speak = MagicMock()
        mock_voice.listen.side_effect = [
            "track my gym workouts",
            "react and vite",
            "web dashboard",
        ]
        refined, assumptions = clarify_request("build something", voice=mock_voice)
        assert "gym workouts" in refined
        assert "react and vite" in refined


class TestTemplateMatching:
    def test_match_flask_api(self):
        spec = match_template("build a flask rest api service")
        assert spec is not None
        assert spec.template_used == "flask_api"
        assert "app.py" in [f.name for f in spec.files]

    def test_match_react_vite(self):
        spec = match_template("create a react vite dashboard")
        assert spec is not None
        assert spec.template_used == "react_vite"
        assert "package.json" in [f.name for f in spec.files]

    def test_match_static_site(self):
        spec = match_template("make a static website landing page")
        assert spec is not None
        assert spec.template_used == "static_site"
        assert "index.html" in [f.name for f in spec.files]

    def test_match_cli_tool(self):
        spec = match_template("write a python command line cli tool")
        assert spec is not None
        assert spec.template_used == "cli_tool"
        assert "main.py" in [f.name for f in spec.files]


class TestSpecGeneration:
    def test_strip_markdown_fences(self):
        raw = "```json\n{\"title\": \"Test\", \"stack\": \"py\"}\n```"
        assert _strip_markdown_fences(raw) == '{"title": "Test", "stack": "py"}'

    def test_generate_spec_with_llm(self):
        mock_brain = MagicMock()
        llm_payload = {
            "title": "Weather Tracker",
            "stack": "python-fastapi",
            "summary": "Fetches current weather forecasts.",
            "run_command": "uvicorn main:app",
            "test_command": "pytest",
            "dependencies": ["fastapi", "httpx"],
            "files": [
                {"name": "main.py", "purpose": "API routes"},
                {"name": "test_main.py", "purpose": "Tests"},
            ],
            "acceptance_criteria": ["Endpoint /weather returns JSON"],
        }
        mock_brain.ask.return_value = f"```json\n{json.dumps(llm_payload)}\n```"

        spec = generate_project_spec("weather forecast service", brain=mock_brain)
        assert spec.title == "Weather Tracker"
        assert spec.stack == "python-fastapi"
        assert len(spec.files) == 2

    def test_generate_spec_repair_on_invalid_json(self):
        mock_brain = MagicMock()
        # First call fails JSON parsing, second call succeeds
        mock_brain.ask.side_effect = [
            "Sure! Here is the plan: title: Weather, stack: py (invalid JSON)",
            json.dumps({
                "title": "Repaired Weather",
                "stack": "python",
                "summary": "Repaired summary",
                "run_command": "python main.py",
                "test_command": "pytest",
                "files": [{"name": "main.py", "purpose": "entry"}],
                "acceptance_criteria": ["starts cleanly"],
            }),
        ]
        spec = generate_project_spec("weather app", brain=mock_brain)
        assert spec.title == "Repaired Weather"
        assert len(spec.files) == 1

    def test_generate_spec_bulletproof_fallback(self):
        mock_brain = MagicMock()
        mock_brain.ask.side_effect = Exception("LLM connection timed out")
        spec = generate_project_spec("custom machine learning tool", brain=mock_brain)
        assert spec is not None
        assert spec.template_used == "builtin_fallback"
        assert len(spec.files) >= 3


class TestScaffoldingAndFiles:
    def test_write_project_spec_files(self, tmp_path):
        spec = ProjectSpec(
            title="Demo Service",
            stack="python-flask",
            summary="Test service summary",
            run_command="python app.py",
            test_command="pytest",
            files=[ProjectFileSpec("app.py", "Main logic")],
            acceptance_criteria=["Server responds to GET /"],
            assumptions_made=["Assumed web interface"],
        )
        write_project_spec_files(spec, str(tmp_path))

        plan_f = tmp_path / "PLAN.md"
        acc_f = tmp_path / "ACCEPTANCE.md"
        agent_f = tmp_path / "AGENTS.md"

        assert plan_f.exists()
        assert acc_f.exists()
        assert agent_f.exists()

        assert "Demo Service" in plan_f.read_text(encoding="utf-8")
        assert "Assumed web interface" in plan_f.read_text(encoding="utf-8")
        assert "- [ ] Server responds to GET /" in acc_f.read_text(encoding="utf-8")
        assert "Do-Not-Touch Folders" in agent_f.read_text(encoding="utf-8")

    def test_scaffold_project_with_flask_template(self, tmp_path):
        spec = match_template("flask api")
        assert spec is not None

        ws = tmp_path / "scaffold_test"
        ok = scaffold_project(spec, str(ws))
        assert ok is True

        # Check template files copied
        assert (ws / "app.py").exists()
        assert (ws / "requirements.txt").exists()
        assert (ws / "test_app.py").exists()

        # Check spec files generated
        assert (ws / "PLAN.md").exists()
        assert (ws / "ACCEPTANCE.md").exists()
        assert (ws / "AGENTS.md").exists()

        # Check VS Code tasks.json
        tasks_path = ws / ".vscode" / "tasks.json"
        assert tasks_path.exists()
        tasks_data = json.loads(tasks_path.read_text(encoding="utf-8"))
        assert "tasks" in tasks_data


class TestJobManagerPhaseExecution:
    def test_job_manager_runs_scaffold_phase(self, tmp_path):
        storage_dir = str(tmp_path / "jobs_store")
        ws_root = str(tmp_path / "workspaces")
        mgr = JobManager(storage_dir=storage_dir)

        job = mgr.create_job(
            title="Flask Scaffold Test",
            request_text="build a flask api for users",
            workspace_root=ws_root,
        )
        assert job.metadata.get("spec") is not None
        assert "scaffold" in [p.name for p in job.phase_list]

        mgr.submit_job(job)

        # Wait for worker thread to process at least the scaffold phase
        for _ in range(60):
            time.sleep(0.1)
            updated = mgr.store.load(job.id)
            if updated and updated.current_phase >= 1:
                break

        updated_job = mgr.store.load(job.id)
        assert updated_job is not None
        assert updated_job.current_phase >= 1

        # Check that workspace has PLAN.md, ACCEPTANCE.md, AGENTS.md, and template files
        ws = updated_job.workspace_path
        assert os.path.exists(os.path.join(ws, "PLAN.md"))
        assert os.path.exists(os.path.join(ws, "ACCEPTANCE.md"))
        assert os.path.exists(os.path.join(ws, "AGENTS.md"))
        assert os.path.exists(os.path.join(ws, "app.py"))

        mgr.shutdown()

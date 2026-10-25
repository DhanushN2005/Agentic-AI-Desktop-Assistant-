"""Unit and integration tests for Phase 3: Code Generation & Auto-Install."""
import json
import os
from unittest.mock import MagicMock
import pytest

from core.jobs.generator import (
    CodeGenerator,
    MAX_FILES_PER_PROJECT,
    MAX_FILE_SIZE_BYTES,
    neutralize_secrets,
    strip_fences_and_prose,
    validate_syntax,
)
from core.jobs.models import BuildJob, JobPhase, JobStatus
from core.jobs.planner import ProjectFileSpec, ProjectSpec


class TestSyntaxValidation:
    def test_python_syntax_valid(self):
        valid_py = "def add(a: int, b: int) -> int:\n    return a + b\n"
        ok, err = validate_syntax("math_utils.py", valid_py)
        assert ok is True
        assert err is None

    def test_python_syntax_invalid(self):
        broken_py = "def broken(:\n    pass\n"
        ok, err = validate_syntax("broken.py", broken_py)
        assert ok is False
        assert "SyntaxError" in err

    def test_json_syntax_valid(self):
        valid_json = '{"name": "flexie", "count": 42}'
        ok, err = validate_syntax("data.json", valid_json)
        assert ok is True
        assert err is None

    def test_json_syntax_invalid(self):
        broken_json = '{"name": "flexie", broken}'
        ok, err = validate_syntax("data.json", broken_json)
        assert ok is False
        assert "JSONDecodeError" in err

    def test_html_syntax_valid(self):
        valid_html = "<!DOCTYPE html><html><body><h1>Hello</h1></body></html>"
        ok, err = validate_syntax("index.html", valid_html)
        assert ok is True

    def test_html_syntax_invalid(self):
        broken_html = "just a plain text string without any tags"
        ok, err = validate_syntax("index.html", broken_html)
        assert ok is False
        assert "lacks valid HTML tags" in err

    def test_js_syntax_unbalanced_brackets(self):
        broken_js = "function test() { console.log('hello');"
        ok, err = validate_syntax("app.js", broken_js)
        assert ok is False
        assert "Unclosed" in err or "Unbalanced" in err


class TestFenceAndProseStripping:
    def test_strip_markdown_code_fence(self):
        raw = "Here is the code:\n```python\ndef hello():\n    return 'hi'\n```\nHope this helps!"
        clean = strip_fences_and_prose("hello.py", raw)
        assert clean == "def hello():\n    return 'hi'"

    def test_strip_stray_conversational_lines(self):
        raw = "Sure, I have generated this file for you:\nprint('running')"
        clean = strip_fences_and_prose("script.py", raw)
        assert clean == "print('running')"

    def test_strip_duckduckgo_search_attribution(self):
        raw = "Based on my web search results, here is the code:\nx = 10\ny = 20"
        clean = strip_fences_and_prose("calc.py", raw)
        assert clean == "x = 10\ny = 20"


class TestSecretNeutralization:
    def test_openai_key_replaced(self, tmp_path):
        code = 'client = OpenAI(api_key="sk-1234567890123456789012345")'
        clean, detected = neutralize_secrets(code, str(tmp_path), "client.py")
        assert "OPENAI_API_KEY" in detected
        assert 'os.getenv("OPENAI_API_KEY", "")' in clean
        assert "sk-1234567890123456789012345" not in clean

        # Check .env.example written
        env_ex = tmp_path / ".env.example"
        assert env_ex.exists()
        assert "OPENAI_API_KEY=your_openai_api_key_here" in env_ex.read_text(encoding="utf-8")

    def test_groq_key_in_javascript(self, tmp_path):
        code = 'const apiKey = "gsk_1234567890123456789012345";'
        clean, detected = neutralize_secrets(code, str(tmp_path), "api.js")
        assert "GROQ_API_KEY" in detected
        assert "process.env.GROQ_API_KEY" in clean
        assert "gsk_1234567890123456789012345" not in clean


class TestCodeGeneratorExecution:
    def test_token_budget_abort(self, tmp_path):
        gen = CodeGenerator(token_budget=1000)
        job = BuildJob(title="Budget Test", workspace_path=str(tmp_path), tokens_used=1500)
        file_spec = ProjectFileSpec("app.py", "Main")
        spec = ProjectSpec("Test", "python", "desc", "python app.py", "pytest", [file_spec])

        mock_brain = MagicMock()
        ok, err = gen.generate_single_file(job, file_spec, mock_brain, spec)
        assert ok is False
        assert "Token budget exceeded" in err
        mock_brain.ask.assert_not_called()

    def test_file_count_cap_abort(self, tmp_path):
        gen = CodeGenerator()
        ws = tmp_path / "crowded"
        ws.mkdir()
        # Create 60 dummy files
        for i in range(MAX_FILES_PER_PROJECT):
            (ws / f"file_{i}.txt").write_text("x", encoding="utf-8")

        job = BuildJob(title="Cap Test", workspace_path=str(ws))
        file_spec = ProjectFileSpec("overflow.py", "Extra")
        spec = ProjectSpec("Test", "python", "desc", "python app.py", "pytest", [file_spec])

        mock_brain = MagicMock()
        ok, err = gen.generate_single_file(job, file_spec, mock_brain, spec)
        assert ok is False
        assert "File count limit reached" in err

    def test_generate_single_file_success(self, tmp_path):
        gen = CodeGenerator()
        job = BuildJob(title="Gen Test", workspace_path=str(tmp_path))
        file_spec = ProjectFileSpec("calculator.py", "Math utilities")
        spec = ProjectSpec("Math", "python", "desc", "python app.py", "pytest", [file_spec])

        mock_brain = MagicMock()
        mock_brain.ask.return_value = "```python\ndef multiply(a: int, b: int) -> int:\n    return a * b\n```"

        ok, err = gen.generate_single_file(job, file_spec, mock_brain, spec)
        assert ok is True
        assert err == ""

        calc_file = tmp_path / "calculator.py"
        assert calc_file.exists()
        assert "def multiply" in calc_file.read_text(encoding="utf-8")
        assert job.tokens_used > 0

    def test_repair_pass_recovers_broken_syntax(self, tmp_path):
        gen = CodeGenerator()
        job = BuildJob(title="Repair Test", workspace_path=str(tmp_path))
        file_spec = ProjectFileSpec("service.py", "Backend service")
        spec = ProjectSpec("Service", "python", "desc", "python app.py", "pytest", [file_spec])

        mock_brain = MagicMock()
        # Call 1: intent plan, Call 2: broken code, Call 3: fixed code
        mock_brain.ask.side_effect = [
            "Plan for service.py",
            "```python\ndef broken(:\n    pass\n```",
            "```python\ndef fixed():\n    return True\n```",
        ]

        ok, err = gen.generate_single_file(job, file_spec, mock_brain, spec)
        assert ok is True
        assert err == ""

        service_file = tmp_path / "service.py"
        assert service_file.exists()
        assert "def fixed():" in service_file.read_text(encoding="utf-8")

    def test_repair_failure_fails_phase(self, tmp_path):
        gen = CodeGenerator()
        job = BuildJob(title="Fail Test", workspace_path=str(tmp_path))
        file_spec = ProjectFileSpec("hopeless.py", "Broken file")
        spec = ProjectSpec("Hopeless", "python", "desc", "python app.py", "pytest", [file_spec])

        mock_brain = MagicMock()
        # Call 1: intent plan, Call 2: broken code, Call 3: repair attempt also broken
        mock_brain.ask.side_effect = [
            "Plan for hopeless.py",
            "```python\ndef broken(:\n    pass\n```",
            "```python\ndef still_broken(:\n    pass\n```",
        ]

        ok, err = gen.generate_single_file(job, file_spec, mock_brain, spec)
        assert ok is False
        assert "Syntax error persisted after repair" in err
        assert not (tmp_path / "hopeless.py").exists()

    def test_generate_all_files_lifecycle(self, tmp_path):
        gen = CodeGenerator()
        f1 = ProjectFileSpec("mod1.py", "Module 1")
        f2 = ProjectFileSpec("mod2.py", "Module 2")
        spec = ProjectSpec("Multi", "python", "desc", "python app.py", "pytest", [f1, f2])

        job = BuildJob(title="Multi Test", workspace_path=str(tmp_path))
        job.metadata["spec"] = spec.to_dict()

        mock_brain = MagicMock()
        mock_brain.ask.return_value = "```python\nx = 1\n```"

        phase = JobPhase(name="core_logic")
        ok = gen.generate_all_files(job, mock_brain, phase)
        assert ok is True
        assert "Generated 2 source files" in phase.output
        assert (tmp_path / "mod1.py").exists()
        assert (tmp_path / "mod2.py").exists()

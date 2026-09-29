"""Unit and integration tests for Phase 4: Verification & Self-Healing."""
import os
import socket
import time
from unittest.mock import MagicMock, patch
import pytest

from core.jobs.verifier import (
    SelfHealer,
    detect_stack,
    find_free_port,
    get_project_venv,
    install_dependencies,
    run_tests,
    start_and_smoke_test,
    verify_and_update_acceptance,
)


class TestStackDetection:
    def test_detect_python_requirements(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask", encoding="utf-8")
        assert detect_stack(str(tmp_path)) == "python"

    def test_detect_python_source(self, tmp_path):
        (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
        assert detect_stack(str(tmp_path)) == "python"

    def test_detect_node(self, tmp_path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert detect_stack(str(tmp_path)) == "node"

    def test_detect_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
        assert detect_stack(str(tmp_path)) == "rust"

    def test_detect_java(self, tmp_path):
        (tmp_path / "pom.xml").write_text("", encoding="utf-8")
        assert detect_stack(str(tmp_path)) == "java"

    def test_detect_static(self, tmp_path):
        (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
        assert detect_stack(str(tmp_path)) == "static"


class TestPortAllocationAndSmokeTest:
    def test_find_free_port(self):
        p1 = find_free_port()
        p2 = find_free_port()
        assert isinstance(p1, int)
        assert p1 > 1024
        # Verify port is usable
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", p1))

    def test_smoke_test_with_http_server(self, tmp_path):
        (tmp_path / "index.html").write_text("<!DOCTYPE html><html><body><h1>Flexie Test</h1></body></html>", encoding="utf-8")
        port = find_free_port()
        run_cmd = f"python -m http.server {port}"

        ok, msg = start_and_smoke_test(
            workspace_path=str(tmp_path),
            stack="static",
            run_command=run_cmd,
            port=port,
            max_wait_seconds=5.0,
        )
        assert ok is True
        assert "successfully started" in msg

        # Ensure server process tree is cleanly killed
        time.sleep(0.5)
        # Port should be free again
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", port))


class TestSelfHealing:
    def test_duplicate_error_signature_stops_early(self):
        healer = SelfHealer(max_attempts=3)
        mock_brain = MagicMock()

        err = "Traceback (most recent call last):\n  File 'app.py', line 10, in <module>\nNameError: name 'x' is not defined"

        # Attempt 1
        with patch.object(healer, "attempt_heal", wraps=healer.attempt_heal):
            with patch("core.jobs.verifier.resolve_in_root", side_effect=Exception("stop")):
                ok1, _ = healer.attempt_heal("ws", err, "app.py", mock_brain)
                assert ok1 is False

            # Attempt 2 with identical error
            ok2, msg2 = healer.attempt_heal("ws", err, "app.py", mock_brain)
            assert ok2 is False
            assert "identical error signature" in msg2

    def test_successful_self_heal_patch(self, tmp_path):
        healer = SelfHealer(max_attempts=3)
        broken_file = tmp_path / "math_ops.py"
        broken_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

        mock_brain = MagicMock()
        mock_brain.ask.return_value = "```python\ndef add(a, b):\n    return a + b\n```"

        err = "AssertionError: assert add(1, 2) == 3 but got -1"
        ok, msg = healer.attempt_heal(str(tmp_path), err, "math_ops.py", mock_brain)
        assert ok is True
        assert "Applied fix" in msg
        assert "return a + b" in broken_file.read_text(encoding="utf-8")


class TestAcceptanceUpdating:
    def test_verify_and_update_acceptance(self, tmp_path):
        acc = tmp_path / "ACCEPTANCE.md"
        acc.write_text(
            "# Acceptance\n\n- [ ] Server starts cleanly\n- [ ] Unit tests pass\n- [ ] Database migrated\n",
            encoding="utf-8",
        )

        verify_and_update_acceptance(str(tmp_path), ["Server starts cleanly", "tests pass"])

        content = acc.read_text(encoding="utf-8")
        assert "- [x] Server starts cleanly" in content
        assert "- [x] Unit tests pass" in content
        assert "- [ ] Database migrated" in content

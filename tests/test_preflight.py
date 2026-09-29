"""Unit tests for Phase 0 Preflight & Path Jail security checks."""
import os
import shutil
import sys
from unittest.mock import patch, MagicMock
import pytest

from utils.path_jail import resolve_in_root, validate_path_jail, is_basename_safe, is_system_location
from utils.preflight import run_preflight, _check_binary, _resolve_code_cli


class TestPathJail:
    def test_valid_nested_path(self, tmp_path):
        sub = tmp_path / "src" / "main.py"
        sub.parent.mkdir(parents=True)
        sub.write_text("print('hello')", encoding="utf-8")
        res = resolve_in_root("src/main.py", str(tmp_path))
        assert os.path.exists(res)
        assert res == str(sub.resolve())

    def test_validate_path_jail_alias(self, tmp_path):
        sub = tmp_path / "app.py"
        sub.write_text("x = 1", encoding="utf-8")
        assert validate_path_jail("app.py", str(tmp_path)) == str(sub.resolve())

    def test_reject_dot_dot_escape(self, tmp_path):
        with pytest.raises(ValueError, match="path escapes workspace root"):
            resolve_in_root("../outside.txt", str(tmp_path))

    def test_reject_absolute_path_escape(self, tmp_path):
        outside = os.path.abspath(os.sep)
        with pytest.raises(ValueError, match="path escapes workspace root"):
            resolve_in_root(outside, str(tmp_path))

    def test_reject_reserved_windows_names(self, tmp_path):
        for name in ("con", "nul", "prn", "aux", "com1", "lpt1", "nul.txt"):
            with pytest.raises(ValueError, match="reserved Windows device name"):
                resolve_in_root(name, str(tmp_path))

    def test_is_basename_safe(self):
        assert is_basename_safe("my_module.py") is True
        assert is_basename_safe("package-v1.tar.gz") is True
        assert is_basename_safe("../evil.py") is False
        assert is_basename_safe("sub/folder") is False
        assert is_basename_safe("con.txt") is False
        assert is_basename_safe("NUL") is False
        assert is_basename_safe("aux.json") is False
        assert is_basename_safe("") is False
        assert is_basename_safe(" " * 5) is False
        assert is_basename_safe("a" * 300) is False

    def test_is_system_location(self):
        assert is_system_location(r"C:\Windows\System32") is True
        assert is_system_location(r"C:\Program Files") is True
        assert is_system_location(r"C:\\") is True


class TestPreflight:
    def test_run_preflight_real_system(self, tmp_path):
        res = run_preflight(workspace_root=str(tmp_path))
        assert isinstance(res, dict)
        assert "overall_ok" in res
        assert "checks" in res
        assert "spoken_summary" in res
        assert "missing_tools" in res
        checks = res["checks"]
        for key in ("python", "git", "node", "npm", "pip", "docker", "code", "ollama", "internet", "disk_space", "workspace_write"):
            assert key in checks
            assert "ok" in checks[key]
            assert "message" in checks[key]
            assert "spoken" in checks[key]

    def test_preflight_low_disk_space(self, tmp_path):
        mock_usage = MagicMock()
        # 1 GB free (< 2 GB required)
        mock_usage.free = 1 * (1024 ** 3)
        with patch("shutil.disk_usage", return_value=mock_usage):
            res = run_preflight(workspace_root=str(tmp_path))
            assert res["checks"]["disk_space"]["ok"] is False
            assert res["overall_ok"] is False
            assert any("disk space" in err.lower() for err in res["errors"])

    def test_preflight_ollama_reachable_mock(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"models": [{"name": "deepseek-r1:latest"}, {"name": "llama3:latest"}]}'
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = run_preflight(workspace_root=str(tmp_path))
            assert res["checks"]["ollama"]["ok"] is True
            assert res["checks"]["ollama"]["reachable"] is True
            assert "deepseek-r1:latest" in res["checks"]["ollama"]["models"]

    def test_preflight_ollama_unreachable_never_crashes(self, tmp_path):
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            res = run_preflight(workspace_root=str(tmp_path))
            assert res["checks"]["ollama"]["ok"] is False
            assert res["checks"]["ollama"]["reachable"] is False
            assert res["checks"]["ollama"]["models"] == []

    def test_preflight_missing_binary_reporting(self):
        res = _check_binary("nonexistent_binary_xyz_123")
        assert res["installed"] is False
        assert res["path"] is None
        assert "not installed" in res["message"]
        assert "not installed" in res["spoken"]

    def test_preflight_unwritable_workspace(self, tmp_path):
        unwritable_dir = tmp_path / "readonly_dir"
        unwritable_dir.mkdir()
        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            res = run_preflight(workspace_root=str(unwritable_dir))
            assert res["checks"]["workspace_write"]["ok"] is False
            assert res["overall_ok"] is False

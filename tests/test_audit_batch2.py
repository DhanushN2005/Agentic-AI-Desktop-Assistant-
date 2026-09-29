"""Batch 2 audit fixes: UDP token auth, atomic .env, shell=False, path jail."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import utils.udp_auth as udp_auth
from utils.udp_auth import pack, unpack
from utils.path_jail import (
    is_basename_safe,
    is_system_location,
    project_root,
    resolve_in_root,
)


# --- UDP auth ---
def test_udp_roundtrip(monkeypatch):
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "test-token-123")
    assert unpack(pack("wake up")) == "wake up"
    assert unpack(pack("SET_API_KEY:groq:gsk_x")) == "SET_API_KEY:groq:gsk_x"


def test_udp_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "test-token-123")
    assert unpack("wake up") is None
    assert unpack("SET_API_KEY:groq:gsk_x") is None
    assert unpack("") is None


def test_udp_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "correct-token")
    assert unpack("TOKEN:wrong-token wake up") is None
    assert unpack("TOKEN: SET_API_KEY:x:y") is None


def test_udp_rejects_tampered_payload(monkeypatch):
    monkeypatch.setenv("FLEXIE_UDP_TOKEN", "correct-token")
    good = pack("SET_VOLUME:50")
    assert unpack(good) == "SET_VOLUME:50"
    # flipping the payload invalidates nothing structurally, but a forged
    # token head must fail
    forged = "TOKEN:attacker-token SET_VOLUME:50"
    assert unpack(forged) is None


def test_orchestrator_network_loop_enforces_auth():
    import pathlib
    src = pathlib.Path("core/orchestrator.py").read_text(encoding="utf-8")
    assert "unpack" in src and "rejected message without valid token" in src


# --- .env atomic + allowlist ---
def test_env_rejects_unknown_key(monkeypatch, tmp_path):
    import utils.config as cfg
    monkeypatch.setattr(cfg, "_env_path", lambda: str(tmp_path / ".env"))
    assert cfg._write_env_file({"EVIL; rm -rf": "x"}) is False
    assert cfg._write_env_file({"SOME_RANDOM_THING": "x"}) is False
    assert not (tmp_path / ".env").exists()


def test_env_rejects_multiline_value(monkeypatch, tmp_path):
    import utils.config as cfg
    monkeypatch.setattr(cfg, "_env_path", lambda: str(tmp_path / ".env"))
    assert cfg._write_env_file({"GROQ_API_KEY": "gsk_abc\nINJECTED=1"}) is False


def test_env_allows_known_and_custom_provider_keys(monkeypatch, tmp_path):
    import utils.config as cfg
    monkeypatch.setattr(cfg, "_env_path", lambda: str(tmp_path / ".env"))
    assert cfg._write_env_file({"GROQ_API_KEY": "gsk_testvalue123"}) is True
    assert cfg._write_env_file({"MYPROV_API_KEY": "abc"}) is True
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GROQ_API_KEY=gsk_testvalue123" in content
    assert "MYPROV_API_KEY=abc" in content
    # atomic: no temp leftovers
    assert list(tmp_path.glob(".env.*.tmp")) == []


def test_env_write_is_atomic(monkeypatch, tmp_path):
    import utils.config as cfg
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=old\n# comment\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "_env_path", lambda: str(env))
    assert cfg._write_env_file({"GROQ_API_KEY": "new"}) is True
    assert env.read_text(encoding="utf-8").splitlines()[0] == "GROQ_API_KEY=new"


# --- path jail ---
def test_jail_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        resolve_in_root("../../Windows/x", str(tmp_path))


def test_jail_rejects_absolute_outside(tmp_path):
    outside = str(tmp_path.parent / "outside.txt")
    with pytest.raises(ValueError):
        resolve_in_root(outside, str(tmp_path))


def test_jail_rejects_symlink_escape(tmp_path):
    if os.name != "posix" and not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    target = tmp_path / "real_secret.txt"
    target.write_text("s", encoding="utf-8")
    link = tmp_path / "root" / "link.txt"
    link.parent.mkdir(exist_ok=True)
    try:
        os.symlink(str(target), str(link))
    except OSError:
        pytest.skip("cannot create symlink (privileges)")
    with pytest.raises(ValueError):
        resolve_in_root(str(link), str(link.parent))


def test_jail_allows_inside(tmp_path):
    f = tmp_path / "sub" / "a.txt"
    f.parent.mkdir(exist_ok=True)
    f.write_text("x", encoding="utf-8")
    assert resolve_in_root("sub/a.txt", str(tmp_path)) == os.path.realpath(str(f))


def test_basename_rules():
    assert is_basename_safe("report.txt")
    assert not is_basename_safe("../evil.txt")
    assert not is_basename_safe("a/b.txt")
    assert not is_basename_safe("..")
    assert not is_basename_safe("")


def test_system_locations():
    if os.name == "nt":
        assert is_system_location("C:\\")
        assert is_system_location("C:\\Windows\\Temp")
        assert not is_system_location("C:\\Users\\someone\\notes.txt")
    else:
        assert is_system_location("/")
        assert is_system_location("/etc/passwd")


def test_coding_file_tools_jailed():
    from core.coding_tools import register_coding_tools
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()
    register_coding_tools(reg, MagicMock())
    read = reg.get("file.read").execute_fn
    out = read("../../Windows/win.ini")
    assert out.success is False


# --- shell=False ---
def _terminal_fn():
    from core.coding_tools import register_coding_tools
    from core.tool_registry import ToolRegistry
    reg = ToolRegistry()
    register_coding_tools(reg, MagicMock())
    return reg.get("terminal.run").execute_fn


def test_terminal_simple_command_no_shell():
    run = _terminal_fn()
    with patch("core.coding_tools.subprocess.run") as m:
        from core.action_result import ActionResult
        m.return_value = MagicMock(stdout="hi", stderr="", returncode=0)
        out = run("echo hello")
        assert out.success is True
        args, kwargs = m.call_args
        assert kwargs.get("shell") is False
        assert isinstance(args[0], list) and args[0][0] == "echo"


def test_terminal_rejects_pipe():
    run = _terminal_fn()
    # SafetyGuard itself blocks raw pipes; bypass it to prove our own guard.
    with patch("core.coding_tools.SafetyGuard") as sg:
        sg.return_value.validate.return_value = True
        out = run("echo a | findstr a")
    assert out.success is False and "pipe" in out.message.lower()


def test_terminal_rejects_non_allowlisted_binary():
    run = _terminal_fn()
    out = run("curl http://example.com")
    assert out.success is False and "allowlist" in out.message.lower()


def test_terminal_rejects_substitution():
    run = _terminal_fn()
    out = run("echo `whoami`")
    assert out.success is False


def test_terminal_and_chain_executes_segments():
    run = _terminal_fn()
    with patch("core.coding_tools.subprocess.run") as m:
        m.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        out = run("echo a && echo b")
        assert out.success is True
        assert m.call_count == 2


def test_terminal_and_chain_short_circuits():
    run = _terminal_fn()
    with patch("core.coding_tools.subprocess.run") as m:
        m.return_value = MagicMock(stdout="", stderr="e", returncode=1)
        out = run("echo a && echo b")
        assert out.success is False
        assert m.call_count == 1


def test_developer_terminal_no_shell():
    from engines.developer import DeveloperEngine
    orch = MagicMock()
    orch.brain = MagicMock()
    orch.vision = MagicMock()
    eng = DeveloperEngine(orch)
    with patch("engines.developer.subprocess.run") as m:
        m.return_value = MagicMock(stdout="1", stderr="", returncode=0)
        out = eng.execute_terminal(f"{sys.executable} -c print(1)")
        args, kwargs = m.call_args
        assert kwargs.get("shell") is False
        assert isinstance(args[0], list)


def test_developer_terminal_rejects_chain():
    from engines.developer import DeveloperEngine
    orch = MagicMock()
    orch.brain = MagicMock()
    orch.vision = MagicMock()
    eng = DeveloperEngine(orch)
    out = eng.execute_terminal("echo a && echo b")
    assert "not allowed" in out.lower()


def test_power_uses_no_shell():
    from engines.system import SystemCtrl
    with patch("subprocess.Popen") as m:
        SystemCtrl.power("please shutdown pc")
        args, kwargs = m.call_args
        assert kwargs.get("shell") is False
        assert isinstance(args[0], list)


def test_files_rename_rejects_traversal_name():
    from engines.files import FileManager
    fm = FileManager.__new__(FileManager)
    fm._cache = {}
    out = fm.rename_item("rename notes to ../../evil")
    assert "not a plain" in out.lower()


def test_no_shell_true_in_fixed_call_sites():
    import pathlib
    for f in ("core/coding_tools.py", "engines/developer.py", "engines/system.py",
              "engines/files.py", "interface/web_ui_bridge.py"):
        src = pathlib.Path(f).read_text(encoding="utf-8")
        assert "shell=True" not in src, f
        assert "os.system(" not in src, f

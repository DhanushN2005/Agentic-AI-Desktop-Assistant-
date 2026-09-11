import pytest

from core.safety import SafetyGuard


@pytest.fixture(scope="module")
def guard():
    return SafetyGuard()


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr ~",
        "del /s C:\\Users",
        "del /q secret.txt",
        "rd /s C:\\Windows",
        "rmdir /s /q C:\\foo",
        "format c:",
        "mkfs.ext4 /dev/sda",
        "drop table users",
        "drop database main",
        "sudo rm -rf /var",
        "Remove-Item C:\\ -Recurse",
        "Invoke-Expression 'malicious'",
        "powershell -enc ABCDEFG",
        "pwsh -enc ABCDEFG",
        "reg delete HKLM\\Software",
        "taskkill /f /im explorer.exe",
        "shutdown /s /f",
        "play some sexy music",
    ],
)
def test_blocked_destructive_commands(guard, command):
    assert guard.validate(command) is False, f"should block: {command!r}"


@pytest.mark.parametrize(
    "command",
    [
        "open chrome",
        "what is 2 plus 2",
        "delete file notes.txt",
        "create a folder called work",
        "set volume to 30",
        "play some music",
        "hello flexie",
        "search for quantum computing",
    ],
)
def test_allowed_benign_commands(guard, command):
    assert guard.validate(command) is True, f"should allow: {command!r}"


@pytest.mark.parametrize(
    "command",
    [
        "echo hello && rm -rf /",
        "run python script || rm -rf /",
        "shutdown; rm -rf /",
        "echo $(whoami)",
        "run `touch /tmp/x`",
    ],
)
def test_blocked_command_injection(guard, command):
    assert guard.validate(command) is False, f"should block injection: {command!r}"


def test_allowed_semicolon_inside_url(guard):
    # Semicolons inside an http URL are legitimate (e.g. tracking params).
    assert guard.validate("open http://example.com/page?q=1;utm=2") is True


def test_allowed_ampersand_inside_url(guard):
    assert guard.validate("open http://example.com/search?q=a&&b=c") is True


def test_blocked_pipe_even_inside_url(guard):
    # "||" is never a legitimate URL fragment — always blocked.
    assert guard.validate("open http://example.com || shutdown") is False

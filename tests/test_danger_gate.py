import queue
import threading

import pytest

from core.controller import FlexieController
from core.danger_gate import DangerGate


class FakeGlobalMemory:
    def learn_from_history(self, recent_chats: str):
        pass


class FakeMemory:
    def get_context(self, limit=3):
        return ["context line 1", "context line 2"]


class FakeOrchestrator:
    def __init__(self):
        self.active = True
        self._action_thread_id = threading.get_ident()
        self.spoken = []
        self.cmd_queue = queue.Queue()
        self.memory = FakeMemory()


def make_controller(tmp_path, monkeypatch, calls):
    monkeypatch.setattr("core.controller.GlobalMemory", FakeGlobalMemory)
    orch = FakeOrchestrator()

    def fake_speak(text, silent=False):
        orch.spoken.append((text, silent))

    orch.speak = fake_speak
    controller = FlexieController(orch, lambda cmd: calls.append(cmd))
    controller.telemetry.log_path = str(tmp_path / "telemetry.log")
    return orch, controller


# ---------- DangerGate unit tests ----------


@pytest.mark.parametrize(
    "command",
    [
        "delete file report.txt",
        "delete it",
        "erase folder temp",
        "remove file a.txt",
        "wipe drive",
        "clear all",
        "format drive",
        "empty the trash",
        "buy a new laptop",
        "purchase tickets",
        "pay my credit card bill",
        "transfer money",
        "make a payment",
        "send email to boss",
        "send a whatsapp message",
        "unsubscribe from this service",
        "sign out",
        "log out",
        "deactivate account",
    ],
)
def test_detects_destructive_or_irreversible_intents(command):
    assert DangerGate().detect(command) is True, f"should flag: {command!r}"


@pytest.mark.parametrize(
    "command",
    [
        "open chrome",
        "play some music",
        "what is the weather",
        "set volume to 50",
        "shutdown pc",
        "create a folder called work",
        "search for quantum computing",
        "take a screenshot",
        "rename file a.txt to b.txt",
        "",
    ],
)
def test_allows_benign_commands(command):
    assert DangerGate().detect(command) is False, f"should allow: {command!r}"


@pytest.mark.parametrize(
    "text",
    ["yes", "confirm", "ok go ahead", "sure", "yes please", "yeah do it", "go for it"],
)
def test_confirmation_words(text):
    gate = DangerGate()
    assert gate.is_confirmation(text) is True
    assert gate.is_cancellation(text) is False


@pytest.mark.parametrize(
    "text",
    ["cancel", "no", "no, don't do it", "never mind", "forget it", "stop", "skip"],
)
def test_cancellation_words(text):
    gate = DangerGate()
    assert gate.is_cancellation(text) is True
    assert gate.is_confirmation(text) is False


# ---------- Controller confirmation flow ----------


def test_dangerous_command_requires_confirmation(tmp_path, monkeypatch):
    calls = []
    orch, controller = make_controller(tmp_path, monkeypatch, calls)

    status = controller.execute("delete file notes.txt")

    # Blocked from executing; prompt spoken; pending state set.
    assert status == "awaiting_confirmation"
    assert calls == []
    assert controller.pending_confirmation == "delete file notes.txt"
    assert any("confirm" in text for text, _ in orch.spoken)


def test_confirmation_flows_to_original_handle(tmp_path, monkeypatch):
    calls = []
    orch, controller = make_controller(tmp_path, monkeypatch, calls)

    controller.execute("delete file notes.txt")
    status = controller.execute("confirm")

    assert status == "executed"
    assert calls == ["delete file notes.txt"]
    assert controller.pending_confirmation is None


def test_cancellation_aborts_command(tmp_path, monkeypatch):
    calls = []
    orch, controller = make_controller(tmp_path, monkeypatch, calls)

    controller.execute("delete file notes.txt")
    status = controller.execute("no")

    assert status == "cancelled"
    assert calls == []
    assert controller.pending_confirmation is None
    assert any("Cancelled" in text for text, _ in orch.spoken)


def test_unrelated_reply_reprompts(tmp_path, monkeypatch):
    calls = []
    orch, controller = make_controller(tmp_path, monkeypatch, calls)

    controller.execute("delete file notes.txt")
    status = controller.execute("what is the weather")

    assert status == "awaiting_confirmation"
    assert calls == []
    assert controller.pending_confirmation == "delete file notes.txt"


def test_safe_command_bypasses_gate(tmp_path, monkeypatch):
    calls = []
    orch, controller = make_controller(tmp_path, monkeypatch, calls)

    status = controller.execute("open chrome")

    assert status == "executed"
    assert calls == ["open chrome"]
    assert controller.pending_confirmation is None


def test_safety_blocked_command_returns_blocked(tmp_path, monkeypatch):
    calls = []
    orch, controller = make_controller(tmp_path, monkeypatch, calls)

    status = controller.execute("rm -rf /")

    assert status == "blocked"
    assert calls == []
    assert controller.pending_confirmation is None

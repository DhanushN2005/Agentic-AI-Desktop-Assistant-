import pytest

from core.context_memory import ContextMemory


class FakeMemory:
    def __init__(self):
        self.data = {}

    def store(self, key, val):
        self.data[key] = val

    def recall(self, key):
        return self.data.get(key)


@pytest.fixture
def ctx(monkeypatch):
    fake = FakeMemory()
    monkeypatch.setattr("core.context_memory.SystemCtrl.get_active_window_title", lambda: "Visual Studio Code")
    monkeypatch.setattr("core.context_memory.SystemCtrl.get_clipboard", lambda: "clip text")
    return ContextMemory(fake)


def test_loads_defaults_when_memory_empty(ctx):
    assert ctx.last_browser == "chrome"
    assert ctx.last_app is None
    assert ctx.last_response is None


def test_update_persists_registers(ctx):
    ctx.update(app="notepad", query="what is 2+2", last_path=r"C:\temp\doc.txt")
    assert ctx.last_app == "notepad"
    assert ctx.last_query == "what is 2+2"
    assert ctx.last_path == r"C:\temp\doc.txt"
    assert ctx.mem.recall("ctx_last_app") == "notepad"


def test_sync_system_state_captures_focus(ctx):
    assert ctx.focused_app == "Visual Studio Code"
    assert ctx.clipboard_state == "clip text"


def test_resolve_delete_file(tmp_path, ctx):
    target = tmp_path / "notes.txt"
    target.write_text("hello")
    ctx.active_document = str(target)
    resolved = ctx.resolve("delete it")
    assert resolved == f"delete file {target}"


def test_resolve_open_file(tmp_path, ctx):
    target = tmp_path / "report.txt"
    target.write_text("report")
    ctx.last_path = str(target)
    resolved = ctx.resolve("open it")
    assert resolved == f"open {target}"


def test_resolve_paste_response(ctx):
    ctx.last_response = "Here is the generated answer."
    resolved = ctx.resolve("paste it")
    assert resolved == "paste_context_response"


def test_resolve_rename_file(tmp_path, ctx):
    target = tmp_path / "old.txt"
    target.write_text("x")
    ctx.active_document = str(target)
    resolved = ctx.resolve("rename it to new.txt")
    assert resolved == f"rename {target} to new.txt"


def test_resolve_unknown_command_passthrough(ctx):
    assert ctx.resolve("open spotify") == "open spotify"


def test_resolve_write_to_document(ctx):
    ctx.active_document = r"C:\temp\notes.md"
    resolved = ctx.resolve("add these points in that opened document")
    assert resolved == "write_context_query:these points"


def test_resolve_browser_selector_fill(ctx):
    ctx.last_selector = "#email"
    resolved = ctx.resolve("fill it with hello")
    assert resolved == "type in #email with hello"


def test_session_expiry_clears_context(ctx, monkeypatch):
    ctx.active_document = r"C:\temp\old.txt"
    ctx.last_app = "chrome"
    monkeypatch.setattr("time.time", lambda: ctx.session_time + 1000)
    resolved = ctx.resolve("open spotify")
    assert resolved == "open spotify"
    assert ctx.last_app is None

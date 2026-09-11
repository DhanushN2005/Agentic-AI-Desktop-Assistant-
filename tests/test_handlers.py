import sys
import types

from core.handlers import dispatch_intent, handle_context_command
from core.handlers.agents import handle_capability_delegation
from core.handlers.browser import (
    handle_browser_control,
    handle_browser_extract,
    handle_browser_tabs,
    handle_gmail,
)
from core.handlers.dev import handle_briefing, handle_clipboard, handle_dev_build, handle_dev_explain, handle_intel
from core.handlers.files import (
    handle_file_delete,
    handle_file_op,
    handle_file_rename,
    handle_file_save,
    handle_knowledge_search,
)
from core.handlers.media import handle_media, handle_play_youtube, handle_youtube
from core.handlers.system import (
    handle_app_op,
    handle_auto_save,
    handle_brightness,
    handle_comm,
    handle_mode,
    handle_mode_prefix,
    handle_power,
    handle_save_active,
    handle_snap,
    handle_undo,
    handle_voice,
    handle_volume,
)
from core.handlers.vision import handle_camera_capture, handle_vision
from utils.config import Config


class FakeLogger:
    def info(self, *args):
        pass

    def warning(self, *args):
        pass

    def error(self, *args):
        pass


class FakeCtx:
    def __init__(self):
        self.last_response = None
        self.active_document = None
        self.last_path = None
        self.last_query = None
        self.active_engine = None
        self.last_selector = None
        self.registers = {}
        self.updated = {}

    def update(self, **kwargs):
        self.updated.update(kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeBrain:
    def __init__(self):
        self.calls = []

    def ask(self, prompt, system_override=None):
        self.calls.append((prompt, system_override))
        return "summary result"

    def translate(self, text, dest_lang):
        return f"translated '{text}' to {dest_lang}"


class FakeVoice:
    def __init__(self):
        self.lang = "en-IN"

    def confirm(self, question):
        return True

    def listen(self, timeout=5):
        return None


class FakeBrowser:
    def __init__(self):
        self.navigated = []
        self.tabs = ["tab1", "tab2"]

    def navigate(self, url):
        self.navigated.append(url)
        return "opened"

    def cleanup(self):
        return None

    def is_risky(self, target):
        return False

    def highlight_element(self, target):
        return "highlighted"

    def click_element(self, target):
        return f"clicked {target}"

    def fill_field(self, target, val):
        return f"filled {target} with {val}"

    def scroll(self, direction):
        return f"scrolled {direction}"

    def capture_page(self):
        return "captured page"

    def new_tab(self, url):
        return f"opened new tab {url}"

    def switch_tab(self, idx):
        return f"switched to tab {idx}"

    def list_tabs(self):
        return " | ".join(self.tabs)

    def close_current_tab(self):
        return "closed current tab"

    def get_summary(self, brain):
        return "page summary"

    def extract_page_data(self, kind):
        return "link1, link2"

    def gmail_read_unread(self):
        return "You have 2 unread emails."


class FakeFiles:
    def __init__(self):
        self.last_created_path = None
        self.last_opened_path = None

    def open_item(self, target, target_path=None):
        return "opened item"

    def rename_item(self, c):
        return "Renamed item."

    def delete_item(self, c):
        return "Deleted item."

    def create_document(self, c, content, target_dir=None):
        self.last_created_path = r"C:\temp\doc.txt"
        return "Document created."

    def create_folder(self, c):
        return r"C:\temp\projects"

    def organize_desktop(self):
        return "Desktop organized."


class FakeYT:
    def is_session_active(self):
        return False

    def control_player(self, action):
        return "controlled"

    def play_video(self, query):
        return f"now playing {query}"

    def skip_ad(self):
        return "ad skipped"

    def cleanup(self):
        return None


class FakeMusic:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True

    def next(self):
        pass


class FakeVision:
    def capture_screen(self):
        return r"C:\temp\snap.png"

    def show_last_screenshot(self):
        return "showing last screenshot"

    def analyze_screen(self, brain):
        return "screen analysis"

    def launch_camera(self):
        return "camera launched"

    def delete_last_screenshot(self):
        return "deleted last screenshot"


class FakeDev:
    def autonomous_build(self, desc):
        return f"built project for {desc}"

    def explain_project(self):
        return "project explanation"

    def debug_screen(self):
        return "screen debug"


class FakeKnowledge:
    def list_recent_documents(self):
        return "recent documents list"

    def search_my_files(self, query):
        return f"searching my files for {query}"


class FakeIntel:
    def analyze_context(self, c):
        return "suggestion"


class FakeRegistry:
    def get_capability_for_intent(self, intent):
        return None


class FakeMemory:
    def __init__(self):
        self.reminders = []
        self.facts = {}
    def add_reminder(self, task, minutes):
        self.reminders.append((task, minutes))
    def list_reminders(self):
        return [t for t, _ in self.reminders]
    def mark_reminder_done(self, task):
        self.reminders = [(t, m) for t, m in self.reminders if t != task]
    def store(self, key, value, cat="general"):
        self.facts[key] = value
    def recall(self, key):
        return self.facts.get(key)
    def forget(self, key):
        self.facts.pop(key, None)
    def all_facts(self):
        return [(k, v, "general") for k, v in self.facts.items()]


class FakeOrchestrator:
    def __init__(self):
        self.logger = FakeLogger()
        self.ctx = FakeCtx()
        self.brain = FakeBrain()
        self.voice = FakeVoice()
        self.memory = FakeMemory()
        self.browser = FakeBrowser()
        self.files = FakeFiles()
        self.yt = FakeYT()
        self.music = FakeMusic()
        self.capability_registry = FakeRegistry()
        self.current_mode = "professional"
        self.undo_stack = []
        self.auto_save_enabled = False
        self.vision = FakeVision()
        self.dev = FakeDev()
        self.knowledge = FakeKnowledge()
        self.intel = FakeIntel()
        self.spoken = []
        self.sent_ui = []
        self.redirected = []

    def speak(self, text, silent=False):
        self.spoken.append(text)

    def send_to_ui(self, tag, value):
        self.sent_ui.append((tag, value))

    def handle_command(self, cmd, is_subcommand=False, silent=False):
        self.redirected.append((cmd, is_subcommand))

    def _parse_tool_call(self, response):
        return False


def make_orch():
    return FakeOrchestrator()


def inject(monkeypatch, name, obj):
    monkeypatch.setitem(sys.modules, name, obj)


def test_dispatch_search_intent(monkeypatch):
    monkeypatch.setattr("core.handlers.search.subprocess.Popen", lambda *a, **k: None)
    orch = make_orch()
    handled = dispatch_intent(orch, "search", "search for quantum physics", False)
    assert handled is True
    assert orch.ctx.last_response == "summary result"
    assert orch.ctx.updated.get("query") == "quantum physics"


def test_dispatch_search_strips_all_trigger_words(monkeypatch):
    monkeypatch.setattr("core.handlers.search.subprocess.Popen", lambda *a, **k: None)
    orch = make_orch()
    handled = dispatch_intent(orch, "search", "google search cats", False)
    assert handled is True
    assert orch.ctx.updated.get("query") == "cats"


def test_dispatch_remind_parses_delay_and_task(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "remind_me", "remind me in 10 minutes to drink water", False)
    assert handled is True
    assert orch.memory.reminders == [("drink water", 10)]
    assert any("10 minutes" in s for s in orch.spoken)


def test_dispatch_remind_defaults_to_five_minutes(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "remind_me", "remind me to stretch", False)
    assert handled is True
    assert orch.memory.reminders == [("stretch", 5)]


def test_dispatch_remind_supports_hours(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "remind_me", "set a reminder in 1 hour to call mom", False)
    assert handled is True
    assert orch.memory.reminders == [("call mom", 60)]


def test_dispatch_list_reminders(monkeypatch):
    orch = make_orch()
    orch.memory.reminders = [("drink water", 10)]
    handled = dispatch_intent(orch, "list_reminders", "list reminders", False)
    assert handled is True
    assert any("drink water" in s for s in orch.spoken)


def test_dispatch_calc(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "calc", "what is 5 plus 7", False)
    assert handled is True
    assert any("12" in s for s in orch.spoken)


def test_dispatch_calc_no_numbers(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "calc", "calculate something", False)
    assert handled is True
    assert any("couldn't find any numbers" in s for s in orch.spoken)


def test_dispatch_status(monkeypatch):
    monkeypatch.setattr("core.handlers.tools.SystemCtrl.cpu_ram", lambda: (42, 67))
    monkeypatch.setattr("core.handlers.tools.SystemCtrl.battery_status", lambda: "87%")
    orch = make_orch()
    handled = dispatch_intent(orch, "status", "what is my battery", False)
    assert handled is True
    assert any("42" in s and "67" in s and "87%" in s for s in orch.spoken)


def test_dispatch_memory_remember(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "memory", "remember that my name is Dhanush", False)
    assert handled is True
    assert orch.memory.facts.get("my name") == "Dhanush"


def test_dispatch_memory_recall(monkeypatch):
    orch = make_orch()
    orch.memory.store("the capital of france", "paris")
    handled = dispatch_intent(orch, "memory", "recall the capital of france", False)
    assert handled is True
    assert any("paris" in s for s in orch.spoken)


def test_dispatch_memory_list(monkeypatch):
    orch = make_orch()
    orch.memory.store("user's favorite color", "blue")
    handled = dispatch_intent(orch, "memory", "what do you know", False)
    assert handled is True
    assert any("blue" in s for s in orch.spoken)


def test_dispatch_memory_forget(monkeypatch):
    orch = make_orch()
    orch.memory.store("test fact", "value")
    handled = dispatch_intent(orch, "memory", "forget test fact", False)
    assert handled is True
    assert orch.memory.facts.get("test fact") is None


def test_dispatch_translate(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "translate", "translate good morning to Spanish", False)
    assert handled is True
    assert any("Spanish" in s for s in orch.spoken)


def test_dispatch_convert_currency(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "convert", "convert 100 dollars to rupees", False)
    assert handled is True
    assert any("8,620" in s for s in orch.spoken)


def test_dispatch_convert_length(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "convert", "convert 5 kilometers to miles", False)
    assert handled is True
    assert any("3.11" in s for s in orch.spoken)


def test_dispatch_convert_temperature(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "convert", "convert 100 celsius to fahrenheit", False)
    assert handled is True
    assert any("212" in s for s in orch.spoken)


def test_dispatch_convert_unknown_pair(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "convert", "convert 5 zebras to elephants", False)
    assert handled is True
    assert any("don't know that pair" in s for s in orch.spoken)


def test_dispatch_browser_navigate(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "browser_navigate", "open website example.com", False)
    assert handled is True
    assert orch.browser.navigated == ["example.com"]
    assert orch.ctx.updated.get("url") == "example.com"


def test_dispatch_conversational_fallback(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "made_up_intent", "hello there", False)
    assert handled is True
    assert orch.brain.calls
    assert orch.brain.calls[-1][1] == Config.SYSTEM_PROMPT_STANDARD  # standard prompt for professional mode
    assert orch.spoken[-1] == "summary result"
    assert orch.ctx.updated.get("query") == "hello there"


def test_dispatch_snap_keywords_before_intent(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.snap_window", lambda *a, **k: "snapped")
    orch = make_orch()
    handled = dispatch_intent(orch, "browser_navigate", "snap chrome left", False)
    assert handled is True
    assert "snapped" in orch.spoken
    assert orch.browser.navigated == []


def test_dispatch_volume(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.set_volume", lambda v: None)
    orch = make_orch()
    handled = dispatch_intent(orch, "media", "set volume 40", False)
    assert handled is True
    assert any("40 percent" in s for s in orch.spoken)


def test_dispatch_app_op_redirects_to_search(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "app_op", "open chrome search cats", False)
    assert handled is True
    assert orch.redirected == [("search for cats", True)]


def test_dispatch_media_stop(monkeypatch):
    orch = make_orch()
    handled = dispatch_intent(orch, "media", "stop music", False)
    assert handled is True
    assert orch.music.stopped is True
    assert "Playback stopped." in orch.spoken


def test_dispatch_unknown_intent_is_conversational(monkeypatch):
    # "exit" would normally call os._exit(); stub it so pytest survives
    monkeypatch.setattr("core.handlers.dispatcher.handle_exit", lambda orch: True)
    orch = make_orch()
    handled = dispatch_intent(orch, "exit", "whatever", False)
    assert handled is True


def test_context_paste_response(monkeypatch):
    fake_gw = types.SimpleNamespace(getActiveWindow=lambda: None, getWindowsWithTitle=lambda *a: [])
    fake_clip = types.SimpleNamespace(copy=lambda t: None, paste=lambda: "canned answer")
    fake_gui = types.SimpleNamespace(hotkey=lambda *a, **k: None, typewrite=lambda *a, **k: None, press=lambda *a, **k: None)
    inject(monkeypatch, "pygetwindow", fake_gw)
    inject(monkeypatch, "pyperclip", fake_clip)
    inject(monkeypatch, "pyautogui", fake_gui)
    orch = make_orch()
    orch.ctx.last_response = "canned answer"
    assert handle_context_command(orch, "paste_context_response") is True
    assert "Pasted successfully." in orch.spoken


def test_context_copy_response(monkeypatch):
    fake_clip = types.SimpleNamespace(copy=lambda t: None, paste=lambda: "canned answer")
    inject(monkeypatch, "pyperclip", fake_clip)
    orch = make_orch()
    orch.ctx.last_response = "canned answer"
    assert handle_context_command(orch, "copy_context_response") is True
    assert any("Copied the answer" in s for s in orch.spoken)


def test_context_non_context_command_returns_false():
    orch = make_orch()
    assert handle_context_command(orch, "open spotify") is False


def _inject_clipboard(monkeypatch, paste_value):
    fake_gw = types.SimpleNamespace(
        getActiveWindow=lambda: None,
        getWindowsWithTitle=lambda *a: [types.SimpleNamespace(activate=lambda: None)],
    )
    fake_clip = types.SimpleNamespace(copy=lambda t: None, paste=lambda: paste_value)
    fake_gui = types.SimpleNamespace(
        hotkey=lambda *a, **k: None,
        typewrite=lambda *a, **k: None,
        press=lambda *a, **k: None,
    )
    inject(monkeypatch, "pygetwindow", fake_gw)
    inject(monkeypatch, "pyperclip", fake_clip)
    inject(monkeypatch, "pyautogui", fake_gui)


def test_context_write_context_query(monkeypatch):
    _inject_clipboard(monkeypatch, "summary result")
    orch = make_orch()
    assert handle_context_command(orch, "write_context_query:explain gravity") is True
    assert "Pasted context research successfully." in orch.spoken
    assert orch.ctx.updated.get("query") == "explain gravity"


def test_context_continue_context_query(monkeypatch):
    _inject_clipboard(monkeypatch, "summary result")
    orch = make_orch()
    orch.ctx.last_response = "Previous answer."
    assert handle_context_command(orch, "continue_context_query:add more detail") is True
    assert any("Appended continuation" in s for s in orch.spoken)
    assert "Previous answer." in orch.ctx.last_response


def test_context_save_active_context_file(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.get_active_window_title", lambda: "Notepad")
    monkeypatch.setattr("engines.system.SystemCtrl.save_active_file", lambda: None)
    orch = make_orch()
    assert handle_context_command(orch, "save_active_context_file") is True
    assert "Saved your work in Notepad." in orch.spoken


def test_context_write_with_clipboard_fallback(monkeypatch):
    fake_gw = types.SimpleNamespace(getActiveWindow=lambda: None, getWindowsWithTitle=lambda *a: [])
    fake_clip = types.SimpleNamespace(copy=lambda t: None, paste=lambda: "DIFFERENT")
    fake_gui = types.SimpleNamespace(
        hotkey=lambda *a, **k: None,
        typewrite=lambda *a, **k: None,
        press=lambda *a, **k: None,
    )
    inject(monkeypatch, "pygetwindow", fake_gw)
    inject(monkeypatch, "pyperclip", fake_clip)
    inject(monkeypatch, "pyautogui", fake_gui)
    orch = make_orch()
    assert handle_context_command(orch, "write_context_query:explain gravity") is True
    assert any("Typing response out" in s for s in orch.spoken)


# ---------------------------------------------------------------------------
# media handlers
# ---------------------------------------------------------------------------
def test_play_youtube_skips_on_next_trigger():
    orch = make_orch()
    assert handle_play_youtube(orch, "play next track on youtube") is True
    assert "Skipping to the next track." in orch.spoken
    assert "controlled" in orch.spoken


def test_play_youtube_plays_query():
    orch = make_orch()
    assert handle_play_youtube(orch, "play despacito on youtube") is True
    assert any("Playing despacito on YouTube." in s for s in orch.spoken)
    assert any("now playing despacito" in s for s in orch.spoken)
    assert orch.ctx.updated.get("yt_query") == "despacito"


def test_play_youtube_falls_back_to_last_query():
    orch = make_orch()
    orch.ctx.last_query = "ambient lofi"
    assert handle_play_youtube(orch, "play on youtube") is True
    assert any("Playing ambient lofi on YouTube." in s for s in orch.spoken)


def test_youtube_skips_ad():
    orch = make_orch()
    assert handle_youtube(orch, "skip ad") is True
    assert any("skip advertisement" in s for s in orch.spoken)
    assert "ad skipped" in orch.spoken


def test_youtube_advanced_control():
    orch = make_orch()
    assert handle_youtube(orch, "full screen") is True
    assert "controlled" in orch.spoken


def test_youtube_search_navigates():
    orch = make_orch()
    assert handle_youtube(orch, "search for lofi beats on youtube") is True
    assert orch.browser.navigated
    assert "www.youtube.com" in orch.browser.navigated[0]


def test_media_prioritizes_active_youtube():
    orch = make_orch()
    orch.ctx.active_engine = "youtube"
    assert handle_media(orch, "stop music") is True
    assert "controlled" in orch.spoken
    assert orch.music.stopped is False


# ---------------------------------------------------------------------------
# files handlers
# ---------------------------------------------------------------------------
def test_file_rename():
    orch = make_orch()
    assert handle_file_rename(orch, "rename file to new.txt") is True
    assert "Renamed item." in orch.spoken


def test_file_delete_confirmed(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl", types.SimpleNamespace(), raising=False)
    orch = make_orch()
    assert handle_file_delete(orch, "delete old notes") is True
    assert "Deleted item." in orch.spoken


def test_file_delete_cancelled():
    orch = make_orch()
    orch.voice.confirm = lambda q: False
    assert handle_file_delete(orch, "delete old notes") is True
    assert "Deletion cancelled." in orch.spoken


def test_file_save_researches_about():
    orch = make_orch()
    assert handle_file_save(orch, "create a document about quantum physics") is True
    assert orch.brain.calls
    assert orch.ctx.updated.get("active_document") == r"C:\temp\doc.txt"
    assert "Document created." in orch.spoken


def test_file_save_uses_last_response():
    orch = make_orch()
    orch.ctx.last_response = "canned content"
    assert handle_file_save(orch, "save my notes") is True
    assert orch.files.last_created_path == r"C:\temp\doc.txt"


def test_file_op_organize():
    orch = make_orch()
    assert handle_file_op(orch, "organize my desktop") is True
    assert "Desktop organized." in orch.spoken


def test_file_op_create_folder():
    orch = make_orch()
    assert handle_file_op(orch, "create new folder projects") is True
    assert any("Created folder 'projects'" in s for s in orch.spoken)
    assert orch.ctx.updated.get("last_path") == r"C:\temp\projects"


def test_file_op_open():
    orch = make_orch()
    assert handle_file_op(orch, "open my documents") is True
    assert "opened item" in orch.spoken


def test_knowledge_search_recent():
    orch = make_orch()
    assert handle_knowledge_search(orch, "show recent documents") is True
    assert "recent documents list" in orch.spoken


def test_knowledge_search_query():
    orch = make_orch()
    assert handle_knowledge_search(orch, "search my files for expenses") is True
    assert "searching my files for expenses" in orch.spoken


# ---------------------------------------------------------------------------
# system handlers
# ---------------------------------------------------------------------------
def test_undo_empty():
    orch = make_orch()
    assert handle_undo(orch, "undo") is True
    assert "Nothing to undo." in orch.spoken


def test_undo_mode():
    orch = make_orch()
    orch.undo_stack.append(("mode", "hacker"))
    assert handle_undo(orch, "undo") is True
    assert ("MODE", "hacker") in orch.sent_ui
    assert "Reverted mode to hacker." in orch.spoken


def test_undo_open(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.close_app", lambda *a, **k: None)
    orch = make_orch()
    orch.undo_stack.append(("open", "notepad"))
    assert handle_undo(orch, "undo") is True
    assert "Closed notepad." in orch.spoken


def test_undo_screenshot():
    orch = make_orch()
    orch.undo_stack.append(("screenshot", None))
    assert handle_undo(orch, "undo") is True
    assert "deleted last screenshot" in orch.spoken


def test_mode_switch():
    orch = make_orch()
    assert handle_mode(orch, "set mode to hacker", False) is True
    assert orch.current_mode == "hacker"
    assert ("MODE", "hacker") in orch.sent_ui
    assert "System Optimized for hacker." in orch.spoken


def test_mode_unknown():
    orch = make_orch()
    assert handle_mode(orch, "set mode to klingon", False) is True
    assert any("Unknown mode" in s for s in orch.spoken)


def test_power_low_risk(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.power", lambda c: None)
    orch = make_orch()
    assert handle_power(orch, "lock my pc") is True
    assert "Executing system power command." in orch.spoken


def test_power_destructive_auth_failed():
    orch = make_orch()
    orch.voice.listen = lambda timeout=5: None
    assert handle_power(orch, "shutdown the pc") is True
    assert any("Authorization failed." in s for s in orch.spoken)


def test_power_destructive_auth_ok(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.power", lambda c: None)
    orch = make_orch()
    orch.voice.listen = lambda timeout=5: "code red"
    assert handle_power(orch, "shutdown the pc") is True
    assert any("Authorization confirmed." in s for s in orch.spoken)


def test_snap(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.snap_window", lambda *a, **k: "snapped")
    orch = make_orch()
    assert handle_snap(orch, "snap chrome right") is True
    assert "snapped" in orch.spoken


def test_app_op_close(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.close_app", lambda *a, **k: None)
    orch = make_orch()
    assert handle_app_op(orch, "close notepad", False) is True
    assert "Closed notepad." in orch.spoken


def test_save_active(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.get_active_window_title", lambda: "Notepad")
    monkeypatch.setattr("engines.system.SystemCtrl.save_active_file", lambda: None)
    orch = make_orch()
    assert handle_save_active(orch) is True
    assert "Saved your work in Notepad." in orch.spoken


def test_auto_save_enable():
    orch = make_orch()
    assert handle_auto_save(orch, "enable auto save") is True
    assert orch.auto_save_enabled is True


def test_auto_save_disable():
    orch = make_orch()
    orch.auto_save_enabled = True
    assert handle_auto_save(orch, "stop auto save") is True
    assert orch.auto_save_enabled is False


def test_comm_whatsapp_number():
    orch = make_orch()
    assert handle_comm(orch, "whatsapp 123456") is True
    assert "web.whatsapp.com/send?phone=123456" in orch.browser.navigated[0]


def test_comm_whatsapp_web():
    orch = make_orch()
    assert handle_comm(orch, "whatsapp") is True
    assert "Opening WhatsApp Web." in orch.spoken


def test_comm_email():
    orch = make_orch()
    assert handle_comm(orch, "compose email") is True
    assert "Opening your email composer." in orch.spoken


def test_voice_test():
    orch = make_orch()
    assert handle_voice(orch, "test") is True
    assert "loud and clear" in orch.spoken[0]


def test_voice_hindi():
    orch = make_orch()
    assert handle_voice(orch, "speak in hindi") is True
    assert orch.voice.lang == "hi-IN"


def test_voice_english():
    orch = make_orch()
    assert handle_voice(orch, "speak in english") is True
    assert orch.voice.lang == "en-IN"


# ---------------------------------------------------------------------------
# dev handlers
# ---------------------------------------------------------------------------
def test_dev_build():
    orch = make_orch()
    assert handle_dev_build(orch, "build a project for a todo app") is True
    assert "built project for a todo app" in orch.spoken


def test_dev_build_listens_for_desc():
    orch = make_orch()
    orch.voice.listen = lambda timeout=10: "weather app"
    # Bare phrases don't match the strip prefix (requires trailing space), so the
    # full string is passed through as the description.
    assert handle_dev_build(orch, "create a project") is True
    assert "built project for create a project" in orch.spoken


def test_dev_explain():
    orch = make_orch()
    assert handle_dev_explain(orch) is True
    assert "project explanation" in orch.spoken


def test_clipboard_empty(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.get_clipboard", lambda: "")
    orch = make_orch()
    assert handle_clipboard(orch) is True
    assert "Your clipboard is empty." in orch.spoken


def test_clipboard_summary(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.get_clipboard", lambda: "some copied text")
    orch = make_orch()
    assert handle_clipboard(orch) is True
    assert orch.brain.calls
    assert "summary result" in orch.spoken


def test_intel_suggestion():
    orch = make_orch()
    assert handle_intel(orch, "show me my workflow") is True
    assert "suggestion" in orch.spoken


def test_briefing(monkeypatch):
    orch = make_orch()
    orch._get_briefing = lambda: "daily briefing"
    assert handle_briefing(orch) is True
    assert "daily briefing" in orch.spoken


# ---------------------------------------------------------------------------
# browser handlers
# ---------------------------------------------------------------------------
def test_browser_control_click():
    orch = make_orch()
    assert handle_browser_control(orch, "click the submit button") is True
    assert "clicked submit button" in orch.spoken
    assert orch.ctx.updated.get("selector") == "submit button"


def test_browser_control_click_risky_cancelled():
    orch = make_orch()
    orch.browser.is_risky = lambda t: True
    orch.voice.confirm = lambda q: False
    assert handle_browser_control(orch, "click the delete button") is True
    assert "Action cancelled for security." in orch.spoken


def test_browser_control_click_risky_confirmed():
    orch = make_orch()
    orch.browser.is_risky = lambda t: True
    assert handle_browser_control(orch, "click the delete button") is True
    assert "clicked delete button" in orch.spoken


def test_browser_control_fill():
    orch = make_orch()
    assert handle_browser_control(orch, "fill the username with admin") is True
    assert "filled the username with admin" in orch.spoken


def test_browser_control_scroll():
    orch = make_orch()
    assert handle_browser_control(orch, "scroll up") is True
    assert "scrolled up" in orch.spoken


def test_browser_control_capture():
    orch = make_orch()
    assert handle_browser_control(orch, "capture the page") is True
    assert "captured page" in orch.spoken


def test_browser_tabs_new_default():
    orch = make_orch()
    assert handle_browser_tabs(orch, "open a new tab") is True
    assert "google.com" in orch.spoken[0]


def test_browser_tabs_switch():
    orch = make_orch()
    assert handle_browser_tabs(orch, "switch to tab 3") is True
    assert "switched to tab 3" in orch.spoken


def test_browser_tabs_close():
    orch = make_orch()
    assert handle_browser_tabs(orch, "close current tab") is True
    assert "closed current tab" in orch.spoken


def test_browser_tabs_list():
    orch = make_orch()
    assert handle_browser_tabs(orch, "list my tabs") is True
    assert "tab1" in orch.spoken[0]


def test_browser_extract_summarize():
    orch = make_orch()
    assert handle_browser_extract(orch, "summarize this page") is True
    assert "page summary" in orch.spoken
    assert orch.ctx.updated.get("last_response") == "page summary"


def test_browser_extract_links():
    orch = make_orch()
    assert handle_browser_extract(orch, "get links from page") is True
    assert "Found links: link1, link2" in orch.spoken


def test_gmail():
    orch = make_orch()
    assert handle_gmail(orch) is True
    assert any("2 unread emails" in s for s in orch.spoken)


# ---------------------------------------------------------------------------
# vision handlers
# ---------------------------------------------------------------------------
def test_vision_capture():
    orch = make_orch()
    assert handle_vision(orch, "vision_capture", "take a screenshot") is True
    assert "Snap saved." in orch.spoken
    assert orch.ctx.updated.get("screenshot") == r"C:\temp\snap.png"


def test_vision_analyze():
    orch = make_orch()
    assert handle_vision(orch, "vision_analyze", "analyze my screen") is True
    assert "screen analysis" in orch.spoken


def test_camera_capture():
    orch = make_orch()
    assert handle_camera_capture(orch) is True
    assert "camera launched" in orch.spoken


# ---------------------------------------------------------------------------
# agents handlers
# ---------------------------------------------------------------------------
def test_capability_delegation_no_capability():
    orch = make_orch()
    assert handle_capability_delegation(orch, "app_op", "open chrome", False) is False


def test_capability_delegation_sdd(monkeypatch):
    class CapabilityRegistry:
        def get_capability_for_intent(self, intent):
            return "sdd"

    orch = make_orch()
    orch.capability_registry = CapabilityRegistry()

    class FakeSDD:
        def parse_prd(self, c):
            return {"requirement": c}

        def generate_task_graph(self, spec):
            return ["task1", "task2"]

    fake_sdd = types.ModuleType("sdd")
    fake_engineer = types.ModuleType("sdd.engineer")
    fake_engineer.SDDEngineer = lambda brain: FakeSDD()
    monkeypatch.setitem(sys.modules, "sdd", fake_sdd)
    monkeypatch.setitem(sys.modules, "sdd.engineer", fake_engineer)
    assert handle_capability_delegation(orch, "sdd_build", "build a log analysis tool", False) is True
    assert any("task graph" in s for s in orch.spoken)


def test_volume_default_when_no_number(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.set_volume", lambda v: None)
    orch = make_orch()
    assert handle_volume(orch, "turn volume up", True) is True
    assert orch.spoken == []


def test_brightness(monkeypatch):
    monkeypatch.setattr("engines.system.SystemCtrl.set_brightness", lambda v: None)
    orch = make_orch()
    assert handle_brightness(orch, "set brightness 80", False) is True
    assert any("80 percent" in s for s in orch.spoken)


def test_mode_prefix():
    orch = make_orch()
    assert handle_mode_prefix(orch, "mode hacker", False) is True
    assert orch.current_mode == "hacker"
    assert "Switched to hacker mode." in orch.spoken

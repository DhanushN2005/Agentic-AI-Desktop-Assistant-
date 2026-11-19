"""Context awareness: asking when two things are equally likely, acting on what Flexie said, undo, brightness."""
import time
import types

import pytest

from core.context_memory import ContextMemory
from core.handlers import system as sysh
from core.handlers.context import handle_context_command
from core.referents import ReferentStack
from engines.system import SystemCtrl


@pytest.fixture
def files(tmp_path):
    shot = tmp_path / "screenshot_9.png"
    shot.write_bytes(b"x")
    proj = tmp_path / "todo-app"
    proj.mkdir()
    return types.SimpleNamespace(shot=str(shot), proj=str(proj), tmp=tmp_path)


def fresh(files, gap=5):
    ctx = ContextMemory(None)
    ctx.refs.push("project", files.proj, label="todo-app", t=time.time() - gap)    # a finished build (the orchestrator syncs these)
    ctx.update(screenshot=files.shot)
    return ctx


# --------------------------------------------------------------------------- asking instead of guessing
def test_two_equally_likely_things_trigger_a_short_question_and_an_answer_picks_one(files):
    ctx = fresh(files)
    assert ctx.resolve("open it") == "context_ask:Do you mean the screenshot or the project?"
    assert ctx.pending_action == "choose_referent"
    assert ctx.resolve("the project") == "open the project"
    assert ctx.pending_action is None

    ctx = fresh(files)
    ctx.resolve("open that")
    assert ctx.resolve("screenshot") == "show screenshot"
    for answer, expected in (("the first one", "show screenshot"), ("second", "open the project"), ("latest", "show screenshot")):
        ctx = fresh(files)
        ctx.resolve("open it")
        assert ctx.resolve(answer) == expected, answer


def test_cancel_and_unrelated_replies_do_not_leave_flexie_stuck(files):
    ctx = fresh(files)
    ctx.resolve("open it")
    assert ctx.resolve("never mind") == "context_cancel" and ctx.pending_action is None
    ctx = fresh(files)
    ctx.resolve("open it")
    assert ctx.resolve("what time is it") == "what time is it" and ctx.pending_action is None   # a fresh command goes through


def test_the_question_is_spoken_and_far_apart_things_are_not_asked_about(files):
    spoken = []
    orch = types.SimpleNamespace(ctx=fresh(files), speak=lambda t, **k: spoken.append(t))
    assert handle_context_command(orch, orch.ctx.resolve("open it"), False) is True
    assert spoken == ["Do you mean the screenshot or the project?"]
    ctx = fresh(files, gap=400)
    assert ctx.resolve("open it") == "show screenshot" and ctx.resolution_note == "Opening the screenshot."


def test_three_kinds_make_a_three_way_question(files):
    s = ReferentStack()
    now = time.time()
    doc = files.tmp / "a.txt"
    doc.write_text("a")
    s.push("project", files.proj, t=now - 20)
    s.push("file", str(doc), t=now - 10)
    s.push("screenshot", files.shot, t=now - 1)
    assert s.resolve("open it").ask == "Do you mean the screenshot, the file or the project?"


# --------------------------------------------------------------------------- acting on what Flexie said
def test_repeat_shorten_and_translate_act_on_the_last_thing_said():
    ctx = ContextMemory(None)
    ctx.last_spoken = "The forecast for Chennai is thirty-one degrees and humid with a chance of evening showers."
    for phrase in ("say that again", "repeat that", "what did you say", "come again"):
        assert ctx.resolve(phrase) == "repeat_last_reply", phrase
    for phrase, how in (("make it shorter", "shorter"), ("shorten that", "shorter"), ("summarize that", "shorter"), ("in one sentence", "shorter"),
                        ("make that simpler", "simpler"), ("explain it like i'm five", "simpler")):
        assert ctx.resolve(phrase) == f"rewrite_last_reply:{how}", phrase
    assert ctx.resolve("translate that to french") == f"translate {ctx.last_spoken} to french"
    assert ContextMemory(None).resolve("translate that to french") == "translate that to french"   # nothing said yet: left alone


def test_repeat_is_word_for_word_and_bypasses_the_duplicate_filter():
    from core.handlers.context import handle_repeat_last_reply
    from voice.tts_guard import TTSGuard
    guard = TTSGuard()
    spoken = []
    text = "The meeting is at three o'clock."
    guard.should_speak(text)
    assert guard.should_speak(text) is False                 # a normal duplicate within 10 s is dropped...
    orch = types.SimpleNamespace(ctx=types.SimpleNamespace(last_spoken=text), tts_guard=guard,
                                 speak=lambda t, **k: spoken.append(t if guard.should_speak(t) else "DROPPED"))
    handle_repeat_last_reply(orch)
    assert spoken == [text]                                  # ...but a deliberate "say that again" is spoken


def test_rewrite_uses_the_model_on_the_real_text_and_survives_failures():
    from core.handlers.context import handle_rewrite_last_reply
    said, prompts = [], []
    long = "The forecast for Chennai is thirty-one degrees and humid with a chance of evening showers later today."
    orch = types.SimpleNamespace(ctx=types.SimpleNamespace(last_spoken=long), speak=lambda t, **k: said.append(t),
                                 brain=types.SimpleNamespace(ask=lambda p, **k: prompts.append(p) or "31 degrees, humid, showers later."))
    handle_rewrite_last_reply(orch, "shorter")
    assert said == ["31 degrees, humid, showers later."] and long in prompts[0] and "<text>" in prompts[0]
    broken = types.SimpleNamespace(ctx=types.SimpleNamespace(last_spoken=long), speak=lambda t, **k: said.append(t),
                                   brain=types.SimpleNamespace(ask=lambda p, **k: (_ for _ in ()).throw(RuntimeError("no provider"))))
    handle_rewrite_last_reply(broken, "shorter")
    assert "couldn't rewrite" in said[-1] and "Chennai" in said[-1]
    empty = types.SimpleNamespace(ctx=types.SimpleNamespace(last_spoken=None), speak=lambda t, **k: said.append(t))
    handle_rewrite_last_reply(empty, "shorter")
    assert "haven't said" in said[-1]


def test_speak_remembers_what_was_said_for_next_time():
    import inspect

    from core.orchestrator import FlexieOrchestrator as Orchestrator
    assert "self.ctx.last_spoken = full_text" in inspect.getsource(Orchestrator.speak)


# --------------------------------------------------------------------------- undo
class FakeOrch:
    def __init__(self):
        self.undo_stack, self.spoken, self.ui, self.current_mode = [], [], [], "professional"
        self.speak = lambda t, **k: self.spoken.append(t)
        self.send_to_ui = lambda tag, val: self.ui.append((tag, val))

    def push_undo(self, label, fn):
        from core.orchestrator import FlexieOrchestrator as Orchestrator
        Orchestrator.push_undo(self, label, fn)


@pytest.fixture
def hw(monkeypatch):
    state = {"vol": 40, "mute": False, "bri": 50}
    monkeypatch.setattr(SystemCtrl, "get_volume", staticmethod(lambda: state["vol"]))
    monkeypatch.setattr(SystemCtrl, "set_volume", staticmethod(lambda v: state.update(vol=v) or True))
    monkeypatch.setattr(SystemCtrl, "get_mute", staticmethod(lambda: state["mute"]))
    monkeypatch.setattr(SystemCtrl, "set_mute", staticmethod(lambda m: state.update(mute=m) or True))
    monkeypatch.setattr(SystemCtrl, "get_brightness", staticmethod(lambda: state["bri"]))
    monkeypatch.setattr(SystemCtrl, "set_brightness", staticmethod(lambda v: state.update(bri=v)))
    return state


def test_undo_puts_volume_brightness_and_mode_back(hw):
    o = FakeOrch()
    sysh.handle_volume(o, "increase volume", False)
    assert hw["vol"] == 50
    sysh.handle_undo(o, "undo")
    assert hw["vol"] == 40 and o.spoken[-1] == "Volume is back to 40 percent."
    sysh.handle_brightness(o, "increase brightness", False)
    assert hw["bri"] == 65
    sysh.handle_undo(o, "undo that")
    assert hw["bri"] == 50 and "Brightness is back to 50" in o.spoken[-1]
    sysh.handle_mode(o, "hacker mode", False)
    assert o.current_mode == "hacker"
    sysh.handle_undo(o, "undo")
    assert o.current_mode == "professional" and o.ui[-1] == ("MODE", "professional") and o.spoken[-1] == "Back to professional mode."


def test_undo_goes_back_one_step_at_a_time_and_says_when_there_is_nothing(hw):
    o = FakeOrch()
    sysh.handle_volume(o, "volume up", False)
    sysh.handle_volume(o, "volume up", False)
    assert hw["vol"] == 60
    sysh.handle_undo(o, "undo")
    assert hw["vol"] == 50
    sysh.handle_undo(o, "undo")
    assert hw["vol"] == 40
    sysh.handle_undo(o, "undo")
    assert o.spoken[-1] == "Nothing to undo."


def test_an_old_change_is_left_alone_and_a_failing_undo_is_reported(hw):
    o = FakeOrch()
    o.undo_stack.append(("fn", ("the volume change", lambda: "x", time.time() - 3600)))
    sysh.handle_undo(o, "undo")
    assert "a while ago" in o.spoken[-1]
    o.undo_stack.append(("fn", ("the thing", lambda: (_ for _ in ()).throw(OSError("denied")), time.time())))
    sysh.handle_undo(o, "undo")
    assert "couldn't undo the thing" in o.spoken[-1]


def test_new_folder_is_undone_only_while_empty(tmp_path):
    from core.handlers.files import handle_file_op
    made = tmp_path / "Reports"
    made.mkdir()
    o = FakeOrch()
    o.files = types.SimpleNamespace(create_folder=lambda c: str(made))
    o.ctx = types.SimpleNamespace(update=lambda **k: None)
    handle_file_op(o, "create a folder named reports")
    (made / "keep.txt").write_text("x")
    sysh.handle_undo(o, "undo")
    assert made.exists() and "isn't empty" in o.spoken[-1]            # never deletes what you put in it
    (made / "keep.txt").unlink()
    handle_file_op(o, "create a folder named reports")
    sysh.handle_undo(o, "undo")
    assert not made.exists()


@pytest.mark.parametrize("phrase", ["take that back", "undo the last change", "undo", "undo that", "go back", "scratch that"])
def test_undo_phrases_route_to_undo(phrase):
    from core.router import IntentRouter
    assert IntentRouter().route(phrase)[0] == "undo"


# --------------------------------------------------------------------------- brightness
@pytest.mark.parametrize("phrase,expected", [("increase brightness", 65), ("decrease brightness", 35), ("brightness down a lot", 25), ("brighter", 65), ("dimmer", 35),
                                             ("set brightness to 80", 80), ("brightness 20", 20), ("increase brightness by 10", 60), ("max brightness", 100)])
def test_brightness_steps_from_the_real_value(hw, phrase, expected):
    o = FakeOrch()
    sysh.handle_brightness(o, phrase, False)
    assert hw["bri"] == expected, phrase
    assert o.spoken[-1] == f"Brightness is {expected} percent."


def test_brightness_step_without_a_readable_display_is_explained(monkeypatch):
    monkeypatch.setattr(SystemCtrl, "get_brightness", staticmethod(lambda: None))
    set_calls = []
    monkeypatch.setattr(SystemCtrl, "set_brightness", staticmethod(lambda v: set_calls.append(v)))
    o = FakeOrch()
    sysh.handle_brightness(o, "increase brightness", False)
    assert set_calls == [] and "can't read" in o.spoken[-1]
    sysh.handle_brightness(o, "brightness 60", False)
    assert set_calls == [60]


# --------------------------------------------------------------------------- what the dashboard is told
def test_dashboard_snapshot_has_names_and_ages_but_never_full_paths(files):
    ctx = fresh(files)
    snap = ctx.refs.snapshot()
    assert {s["kind"] for s in snap} == {"screenshot", "project"}
    assert all(set(s) == {"kind", "label", "age"} and "\\" not in s["label"] and "/" not in s["label"] for s in snap)
    changes = []
    ctx.refs.on_change = lambda: changes.append(1)
    ctx.note_path(files.shot, "screenshot")
    assert changes


def test_context_is_pushed_to_the_dashboard_and_throttled():
    from core.orchestrator import FlexieOrchestrator as Orchestrator
    sent = []
    fake = types.SimpleNamespace(ctx=types.SimpleNamespace(refs=ReferentStack()), send_to_ui=lambda t, v: sent.append((t, v)))
    Orchestrator._push_context(fake)
    Orchestrator._push_context(fake)                          # within 0.4 s: skipped
    assert len(sent) == 1 and sent[0][0] == "CONTEXT" and sent[0][1] == "[]"


def test_the_page_shows_what_flexie_is_holding_in_mind():
    import pathlib
    page = (pathlib.Path(__file__).resolve().parents[1] / "interface" / "web_ui_v2.html").read_text(encoding="utf-8")
    assert "tag === 'CONTEXT'" in page and "GET_CONTEXT" in page and 'id="mind"' in page and "open that screenshot" in page

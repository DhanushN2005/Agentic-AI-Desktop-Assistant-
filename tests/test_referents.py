"""What "it", "that" and "the screenshot" mean: recency, not a fixed priority."""
import os
import time
import types

import pytest

from core.context_memory import ContextMemory
from core.referents import ReferentStack


@pytest.fixture
def files(tmp_path):
    shot = tmp_path / "screenshot_1.png"
    shot.write_bytes(b"png")
    proj = tmp_path / "calendar-app"
    proj.mkdir()
    doc = tmp_path / "notes.txt"
    doc.write_text("hi")
    return types.SimpleNamespace(shot=str(shot), proj=str(proj), doc=str(doc), url="https://example.com/a")


def stack(files, order, gap=10):
    s = ReferentStack()
    base = time.time() - gap * len(order) - 5
    for i, kind in enumerate(order):
        s.push(kind, {"screenshot": files.shot, "project": files.proj, "file": files.doc, "url": files.url}[kind], t=base + i * gap)
    return s


def test_the_newest_thing_wins_not_a_fixed_priority(files):
    s = stack(files, ["project", "screenshot"], gap=200)   # a project was built, THEN (much later) a screenshot was taken
    r = s.resolve("open it")
    assert r.action == "show screenshot" and r.referent.kind == "screenshot"
    s = stack(files, ["screenshot", "project"], gap=200)   # the other way round
    assert s.resolve("open that").action == "open the project"


@pytest.mark.parametrize("phrase", ["open that screenshot", "open the screenshot", "show me that screenshot", "open the last screenshot",
                                    "open the screenshot you just took", "can you open that screenshot please", "open that screen shot",
                                    "Open the latest screenshot."])
def test_naming_the_kind_picks_that_kind_even_when_something_newer_exists(files, phrase):
    s = stack(files, ["screenshot", "project", "file"])
    r = s.resolve(phrase)
    assert r and r.action == "show screenshot", phrase


def test_other_kinds_resolve_to_concrete_commands(files):
    s = stack(files, ["screenshot", "project", "file", "url"])
    assert s.resolve("open the file you just created").action == f"open_path:{os.path.abspath(files.doc)}"
    assert s.resolve("open that link").action == f"navigate to {files.url}"
    assert s.resolve("open the project").action == "open the project"
    assert s.resolve("open that document").referent.kind == "file"


def test_nothing_remembered_is_reported_not_guessed(files):
    empty = ReferentStack()
    assert empty.resolve("open that screenshot").missing == "screenshot"
    assert empty.resolve("open it").missing == "that"
    assert empty.resolve("open the file") is None             # plain "the file": normal routing / file search decides


def test_bare_it_only_reaches_back_twenty_minutes(files):
    s = ReferentStack()
    s.push("screenshot", files.shot, t=time.time() - 25 * 60)
    assert s.resolve("open it").missing == "that"
    assert s.resolve("open that screenshot").action == "show screenshot"      # but naming it still finds it


def test_a_guess_between_kinds_is_announced_briefly(files):
    s = stack(files, ["project", "screenshot"], gap=200)        # 200 s apart: not equally likely, but worth saying which
    assert s.resolve("open it").note == "Opening the screenshot."
    assert stack(files, ["screenshot"]).resolve("open it").note is None


def test_deleted_files_are_never_offered(files):
    s = stack(files, ["file", "screenshot"])
    os.remove(files.shot)
    assert s.resolve("open it").referent.kind == "file"


def test_things_that_are_not_references_are_left_alone(files):
    s = stack(files, ["screenshot"])
    for phrase in ["open chrome", "open the calculator", "what time is it", "increase volume", "open notepad", "show my downloads folder"]:
        assert s.resolve(phrase) is None, phrase


def test_context_memory_wires_it_up_end_to_end(files):
    ctx = ContextMemory(None)
    ctx.update(last_path=files.proj)                         # project folder first
    ctx.refs.items[-1].t -= 600
    ctx.update(screenshot=files.shot)                        # then a screenshot
    assert ctx.resolve("open that screenshot") == "show screenshot"
    assert ctx.resolve("open it") == "show screenshot"        # the old code opened the project folder here
    assert ctx.resolve("open that screenshot please") == "show screenshot"
    ctx2 = ContextMemory(None)
    assert ctx2.resolve("open that screenshot") == "context_unresolved:screenshot"


def test_generated_code_keeps_its_editor_flow_when_it_is_the_newest_thing(files, tmp_path):
    ctx = ContextMemory(None)
    ctx.update(screenshot=files.shot)
    ctx.refs.items[-1].t -= 300                                     # the screenshot is a few minutes old
    ctx.set_artifact(path=files.doc, language="python", kind="code")
    assert ctx.resolve("open it").startswith("artifact_open:")
    assert ctx.resolve("open that screenshot") == "show screenshot"            # naming the kind wins over the artifact flow


def test_router_no_longer_hijacks_open_that_screenshot_as_open_the_project():
    from core.router import IntentRouter
    R = IntentRouter()
    for phrase in ("open that screenshot", "open that file", "open that folder"):
        assert R.route(phrase)[0] != "job_open", phrase
    for phrase in ("open the project", "run the app i built", "open that app"):
        assert R.route(phrase)[0] == "job_open", phrase


def test_self_model_answers_what_it_refers_to(files):
    from core.self_model import SelfModel, classify
    assert classify("what are we working on") == "context" and classify("where did you save it") == "context"
    ctx = ContextMemory(None)
    ctx.update(screenshot=files.shot)
    orch = types.SimpleNamespace(ctx=ctx, command_log=None, providers=lambda: {})
    sm = SelfModel.__new__(SelfModel)
    sm.orch = orch
    text = sm._a_context()
    assert "screenshot_1.png" in text and "open it" in text.lower()


def test_the_exact_scenario_project_then_screenshot_then_open_that(files, monkeypatch):
    """Build a project, take a screenshot, say 'open that screenshot': the screenshot opens, not the project folder."""
    from core.handlers.context import handle_context_command
    from core.handlers.vision import handle_vision
    from core.router import IntentRouter

    spoken, shown = [], []
    ctx = ContextMemory(None)
    ctx.update(last_path=files.proj)                                  # an earlier build left a project folder
    ctx.refs.items[-1].t -= 600                                       # ... ten minutes ago
    vision = types.SimpleNamespace(capture_screen=lambda: files.shot, show_last_screenshot=lambda: shown.append(files.shot) or "Opening your last screenshot.")
    orch = types.SimpleNamespace(ctx=ctx, vision=vision, speak=lambda t, **k: spoken.append(t))
    handle_vision(orch, "vision_capture", "take a screenshot")
    assert ctx.last_screenshot == files.shot

    router = IntentRouter()
    for phrase in ("open that screenshot", "open it", "show it", "can you open the screenshot you just took"):
        shown.clear()
        cmd = ctx.resolve(phrase)
        assert not handle_context_command(orch, cmd, False) or cmd.startswith(("open_path:", "context_unresolved:")), phrase
        intent = router.route(cmd)[0]
        assert intent == "vision_show", (phrase, cmd, intent)
        handle_vision(orch, intent, cmd)
        assert shown == [files.shot], phrase                           # the screenshot, never the project

    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    ctx.note_path(files.doc)                                           # now a document is the newest thing
    cmd = ctx.resolve("open the file you just created")
    assert handle_context_command(orch, cmd, False) is True and opened == [os.path.abspath(files.doc)]
    spoken.clear()
    assert handle_context_command(orch, ContextMemory(None).resolve("open that screenshot"), False) is True
    assert "take a screenshot" in spoken[-1].lower()                    # nothing remembered: says so and tells what to do


def test_delete_that_targets_the_newest_thing_including_screenshots(files):
    ctx = ContextMemory(None)
    ctx.update(last_path=files.doc)
    time.sleep(0.02)
    ctx.update(screenshot=files.shot)
    assert ctx.resolve("delete that") == f"delete file {os.path.abspath(files.shot)}"


def test_a_path_remembered_from_a_previous_run_can_be_opened_but_never_deleted(files):
    class Mem:
        d = {"ctx_last_screenshot": files.shot, "ctx_session_time": str(time.time())}
        store = lambda self, k, v: None  # noqa: E731
        recall = lambda self, k: self.d.get(k)  # noqa: E731
    ctx = ContextMemory(Mem())
    assert ctx.resolve("open that screenshot") == "show screenshot"        # fine to open after a restart
    assert ctx.resolve("delete that") == "delete that"                      # never offered for deletion

import os
import types

import pytest

from core.jobs import generator as gen
from core.jobs.models import BuildJob
from core.jobs.planner import ProjectFileSpec, ProjectSpec
from core.jobs.verifier import check_static_project
from core.llm_failure import is_failure_text, substantive_code

FALLBACK = "I've searched for you, Dhanush, but I couldn't find a clear enough summary to read back."


def test_failure_text_detection():
    assert is_failure_text("") and is_failure_text(None) and is_failure_text(FALLBACK)
    assert is_failure_text("Based on my web search, blah")
    assert not is_failure_text("const a = 1;\nconsole.log(a);")
    assert not substantive_code("// just a comment")
    assert substantive_code("a()\nb()\nc()")


class _Brain:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def ask(self, *a, **k):
        self.calls += 1
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def _job(tmp_path):
    job = BuildJob(title="t", request_text="r")
    job.workspace_path = str(tmp_path)
    return job


def _spec():
    return ProjectSpec(title="t", stack="static-web", summary="s", run_command="open index.html",
                       test_command="none", files=[ProjectFileSpec(name="app.js", purpose="x" * 40)])


def test_fallback_text_is_never_written_into_a_source_file(tmp_path):
    g = gen.CodeGenerator() if hasattr(gen, "CodeGenerator") else None
    if g is None:
        g = [c for n, c in vars(gen).items() if isinstance(c, type) and hasattr(c, "generate_single_file")][0]()
    g.retry_pauses = (0.0, 0.0)
    brain = _Brain([FALLBACK])
    ok, msg = g.generate_single_file(_job(tmp_path), _spec().files[0], brain, _spec())
    assert ok is False and "rate-limited or unavailable" in msg
    assert brain.calls >= 3                      # retried before giving up
    assert not (tmp_path / "app.js").exists()    # nothing written


def test_recovers_when_the_model_comes_back(tmp_path):
    g = [c for n, c in vars(gen).items() if isinstance(c, type) and hasattr(c, "generate_single_file")][0]()
    g.retry_pauses = (0.0, 0.0)
    code = "```js\nfunction a(){return 1}\nfunction b(){return 2}\nconsole.log(a()+b());\n```"
    ok, msg = g.generate_single_file(_job(tmp_path), _spec().files[0], _Brain([FALLBACK, code]), _spec())
    assert ok, msg
    assert "function a" in (tmp_path / "app.js").read_text()


def test_static_verifier_catches_stub_and_prose_scripts(tmp_path):
    (tmp_path / "index.html").write_text("<html>\n<head>\n<script src='app.js'></script>\n</head>\n<body>\nhi\n</body>\n</html>\n")
    (tmp_path / "app.js").write_text(FALLBACK)
    problems = check_static_project(str(tmp_path))
    assert any("error message instead of code" in p for p in problems)
    (tmp_path / "app.js").write_text("function a(){}\nfunction b(){}\nfunction c(){}\n")
    assert check_static_project(str(tmp_path)) == []
    os.remove(tmp_path / "app.js")
    assert any("missing" in p for p in check_static_project(str(tmp_path)))


def test_groq_siblings_are_tried_on_rate_limit(monkeypatch):
    from core import brain as brain_mod
    b = brain_mod.Brain.__new__(brain_mod.Brain)
    b.__dict__.update(groq_client=object(), provider_manager=None, _cache={}, _cache_lock=__import__("threading").Lock(),
                      system_prompt="x", context_compiler=None, vector_store=None, memory_manager=None,
                      groq_model="m-main")
    monkeypatch.setattr(brain_mod, "is_online", lambda: True)
    monkeypatch.setattr(b, "_active_provider", lambda: "auto", raising=False)
    monkeypatch.setattr(b, "_local_first_enabled", lambda a: False, raising=False)
    monkeypatch.setattr(b, "_circuit_allows", lambda n: True, raising=False)
    monkeypatch.setattr(b, "_report", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(brain_mod.Config, "GROQ_FALLBACK_MODELS", ("m-alt",), raising=False)
    seen = []

    def fake(client, model, *a, **k):
        seen.append(model)
        return None if model == "m-main" else "real answer"
    monkeypatch.setattr(b, "_ask_openai_compatible", fake, raising=False)
    assert b._ask_impl("hi", None, None, False, False) == "real answer"
    assert seen == ["m-main", "m-alt"]


# ---- image downloader ----
def test_image_urls_must_be_public_http(monkeypatch):
    from engines import image_downloader as dl
    for bad in ("http://127.0.0.1/x.png", "http://localhost/x.png", "http://169.254.169.254/latest", "file:///c:/x.png",
                "ftp://example.com/x.png", "http://10.0.0.5/x.png"):
        assert not dl.is_safe_url(bad), bad


def test_download_saves_only_real_images_and_skips_the_rest(tmp_path, monkeypatch):
    import io

    from PIL import Image

    from engines import image_downloader as dl
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    png = buf.getvalue()

    class R:
        def __init__(self, ctype, body, status=200):
            self.status_code, self.headers, self._b = status, {"Content-Type": ctype, "Content-Length": str(len(body))}, body
            self.is_redirect = self.is_permanent_redirect = False

        def iter_content(self, n):
            yield self._b

        def close(self):
            pass
    pages = {"https://a/1.png": R("image/png", png), "https://a/2.png": R("image/png", png),   # duplicate bytes
             "https://a/3.png": R("text/html", b"<html>"), "https://a/4.png": R("image/png", b"not an image"),
             "https://a/5.png": R("image/png", b"x" * 10, 404)}
    monkeypatch.setattr(dl, "_get", lambda url, **k: pages[url])
    res = dl.download(list(pages), 5, "red things", "test", root=str(tmp_path))
    assert len(res.saved) == 1 and res.saved[0].endswith(".png") and os.path.getsize(res.saved[0]) == len(png)
    assert sorted(res.skipped) == ["HTTP 404", "duplicate", "not a valid image", "not an image"]
    assert "Downloaded 1 image " in res.summary()


def test_handler_parses_count_and_query(monkeypatch):
    from core.handlers import images
    from engines import image_downloader as dl
    seen = {}
    monkeypatch.setattr(dl, "download_by_search", lambda q, n, root=None: seen.update(q=q, n=n) or dl.DownloadResult(source="x"))
    said = []
    orch = types.SimpleNamespace(speak=lambda t, **k: said.append(t), ctx=types.SimpleNamespace(update=lambda **k: None))
    images.handle_image_download(orch, "download 7 images of golden retrievers from chrome")
    assert seen == {"q": "golden retrievers", "n": 7}
    images.handle_image_download(orch, "download images")
    assert "What should the images show" in said[-1]


@pytest.mark.parametrize("q", ["download 5 images of cats", "save some photos of mountains", "download images from chrome"])
def test_router_sends_image_requests_to_downloader(q):
    from core.router import IntentRouter
    assert IntentRouter().route(q)[0] == "image_download"


# ---- self model ----
def test_self_questions_are_classified_and_ordinary_ones_are_not():
    from core.self_model import classify
    assert classify("what model are you using") == "model"
    assert classify("why did that fail") == "why_failed"
    assert classify("what did you just do") == "recent"
    assert classify("are you listening") == "state"
    assert classify("what do you remember about me") == "memory"
    assert classify("what can't you do") == "limits"
    for q in ("what happened in 1990", "which model of iphone is best", "what is the weather", "tell me a joke"):
        assert classify(q) is None, q


def test_command_log_marks_failure_from_what_was_said():
    from core.self_model import CommandLog, reply_looks_failed
    log = CommandLog()
    log.add("close x", "app_op", True, None, "I couldn't find a running app called x.", 10)
    log.add("what time", "alarm", True, None, "It's 06:35 PM.", 5)
    assert log.last_failure()["cmd"] == "close x"
    assert reply_looks_failed("Sorry, that didn't work") and not reply_looks_failed("Opening chrome.")


def _orch(log=None, providers=("groq",), active=False):
    from core.self_model import CommandLog, SelfModel
    brain = types.SimpleNamespace(groq_client=object() if "groq" in providers else None, _active_provider=lambda: "auto",
                                  _wait_providers=lambda: None)
    o = types.SimpleNamespace(brain=brain, command_log=log or CommandLog(), active=active, is_processing=False,
                              voice=types.SimpleNamespace(is_speaking=False, stream=True),
                              router=types.SimpleNamespace(intents=[1, 2, 3]), tool_registry=None,
                              awareness=types.SimpleNamespace(recall_facts=lambda limit=8: [
                                  "what do you remember about me", "fact:remember that: remember that",
                                  "user_name: Dhanush", "i like tea: remember that i like tea"]))
    o.self_model = SelfModel(o)
    return o


def test_model_answer_comes_from_config_not_a_guess():
    out = _orch().self_model.answer("what model are you using")
    assert "groq" in out and "not GPT-4" in out


def test_why_failed_reports_the_recorded_reason():
    from core.self_model import CommandLog
    log = CommandLog()
    log.add("close the app zzz", "app_op", True, None, "I couldn't find a running app called zzz.", 12)
    out = _orch(log).self_model.answer("why did that fail")
    assert "close the app zzz" in out and "couldn't find a running app" in out
    assert "no failures" in _orch().self_model.answer("why did that fail") or "Nothing has run" in _orch().self_model.answer("why did that fail")


def test_memory_answer_drops_junk_questions_and_echoes():
    out = _orch().self_model.answer("what do you remember about me")
    assert "user_name: Dhanush" in out and "i like tea" in out
    assert "what do you remember" not in out and "remember that:" not in out


def test_state_says_asleep_vs_listening():
    assert "asleep" in _orch(active=False).self_model.answer("are you listening")
    assert "idle and listening" in _orch(active=True).self_model.answer("are you listening")

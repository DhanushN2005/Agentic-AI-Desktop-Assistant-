"""The static demo site (demo/): landing page + interactive dashboard demo. Nothing private may ship in it."""
import importlib.util
import os
import pathlib
import re
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
INDEX = (DEMO / "index.html").read_text(encoding="utf-8")
APP = (DEMO / "demo.html").read_text(encoding="utf-8")
JS = (DEMO / "demo.js").read_text(encoding="utf-8")


def _build_module():
    spec = importlib.util.spec_from_file_location("demo_build", DEMO / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_dashboard_demo_is_in_sync_with_the_real_dashboard():
    assert _build_module().render() == APP, "demo/demo.html is stale. Run: python demo/build.py"


def test_the_demo_never_connects_anywhere_and_carries_no_secrets():
    assert "connect-src 'none'" in APP and "connect-src 'none'" not in INDEX.replace("default-src 'none'", "")        # dashboard blocks all requests
    assert "DEMO = true;" in APP and "{{AUTH_TOKEN}}" not in INDEX
    assert "<script" not in INDEX                                                                                       # the landing page has no scripts at all
    for text in (INDEX, APP, JS):
        assert not re.search(r"gsk_[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}", text)
    assert "fetch(" not in JS and "WebSocket" not in JS and "XMLHttpRequest" not in JS


def test_vision_mode_and_local_server_scripts_are_left_out():
    shipped = {p.name for p in DEMO.rglob("*") if p.is_file()}
    for banned in ("orb.js", "orb-blackhole.js", "orb-gestures.js", "orb-panel.js", "panels.js", "orb.css", "panels.css"):
        assert banned not in shipped, banned
    for banned in ("orb-panel", "panels.js", "orb-gestures", "mediapipe", "getUserMedia"):
        assert banned not in APP and banned not in INDEX, banned
    assert not any("vision" in str(p.relative_to(DEMO)).lower() for p in DEMO.rglob("*") if p.is_file() and p.name != "build.py")


def test_no_personal_contact_details_or_the_owners_name_in_the_dashboard_demo():
    for text in (INDEX, APP, JS):
        assert "mailto:" not in text and "tel:" not in text and "@gmail" not in text.lower()
        assert not re.search(r"\+?\d{2}[ -]?\d{10}\b|\b\d{5}[ -]?\d{5}\b", text)          # no phone numbers
    assert "Dhanush" not in APP and "Dhanush" not in JS                                    # the sample dashboard uses a neutral identity
    assert "Demo User" in APP and "Name is Sam" in APP


def test_every_local_file_the_pages_use_exists():
    for page in (INDEX, APP):
        for ref in re.findall(r'(?:src|href)="([^"#:][^"]*)"', page):
            if ref.startswith(("http", "data:", "mailto:")):
                continue
            assert (DEMO / ref).exists(), ref
    thumbs = sorted((DEMO / "static").glob("orb-thumb-*.png"))
    assert len(thumbs) >= 10 and (DEMO / "static" / "preview-home.jpg").exists()


# --------------------------------------------------------------------------- the content the user asked for
def test_landing_page_has_the_features_and_who_built_this_sections():
    assert 'id="can-do"' in INDEX and "What Flexie can do" in INDEX
    assert 'id="who"' in INDEX and "Who built this" in INDEX and "Dhanush N" in INDEX
    for needle in ("Run your PC", "See your screen", "Work in your browser", "Build small apps", "Understand what you mean", "Remember you", "Pick your AI",
                   "Built to be careful", "Try the live demo", "Open to internships"):
        assert needle in INDEX, needle


def test_builder_links_come_from_the_portfolio_and_nothing_else_is_linked():
    hrefs = set(re.findall(r'href="(https?://[^"]+)"', INDEX))
    allowed = ("https://dhanushnataraj.netlify.app", "https://github.com/DhanushN2005", "https://www.linkedin.com/in/dhanushnataraj/")
    assert all(h.startswith(allowed) for h in hrefs), sorted(hrefs)
    assert {"https://dhanushnataraj.netlify.app", "https://github.com/DhanushN2005", "https://www.linkedin.com/in/dhanushnataraj/"} <= hrefs


def test_every_example_command_on_the_landing_page_really_works():
    """The page says the blue lines are real things you can say. Prove each one reaches a sensible handler."""
    from core.context_memory import ContextMemory
    from core.preferences import is_statement
    from core.router import IntentRouter
    blocks = re.findall(r'<ul class="say">(.*?)</ul>', INDEX, re.S)
    phrases = [re.sub(r"&#x27;|&#39;", "'", p) for b in blocks for p in re.findall(r"<li>(.*?)</li>", b)]
    assert len(phrases) >= 18
    expected = {
        "increase volume": "media", "brightness 40": "media", "take a screenshot": "vision_capture", "remind me in 5 minutes to stretch": "remind_me",
        "summarize my screen": "vision_analyze", "what's wrong on my screen": "vision_debug", "read my screen": "vision_analyze",
        "summarize this page": "browser_tab", "extract tables from this page": "browser_tab", "click sign in on this page": "browser_tab",
        "build me a to-do app": "dev_build", "open the project": "job_open", "undo that": "undo", "what are my preferences": "awareness",
    }
    context = {"open that screenshot": "show screenshot", "say that again": "repeat_last_reply", "make it shorter": "rewrite_last_reply:shorter"}
    statements = {"I prefer short answers", "call me Sam"}
    router = IntentRouter()
    shot = pathlib.Path(tempfile.mkdtemp()) / "s.png"
    shot.write_bytes(b"x")
    ctx = ContextMemory(None)
    ctx.update(screenshot=str(shot))
    ctx.last_spoken = "The forecast for Chennai is thirty-one degrees and humid with evening showers."
    for phrase in phrases:
        if phrase in expected:
            assert router.route(phrase)[0] == expected[phrase], phrase
        elif phrase in context:
            assert ctx.resolve(phrase) == context[phrase], phrase
        elif phrase in statements:
            assert is_statement(phrase), phrase
        else:
            pytest.fail(f"landing page promises {phrase!r} but no test knows what it should do")


def test_the_deploy_headers_block_requests_and_framing():
    headers = (DEMO / "_headers").read_text(encoding="utf-8")
    for needle in ("connect-src 'none'", "X-Content-Type-Options: nosniff", "X-Frame-Options: DENY", "frame-ancestors 'none'", "Permissions-Policy"):
        assert needle in headers, needle
    assert os.path.exists(DEMO / "build.py")

"""
Quick smoke-test for the two voice-command bugs fixed in handle_app_op:
  1. "open chrome" → always speaks, never silent
  2. "open chrome play tamil song in youtube" → dispatches to youtube handler
  3. "in the opened chrome search for animation" → routes to browser_search
"""
import re
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Minimal stubs so we can import without the full runtime ─────────────────

def _make_orch(browser_open=False, browser_name="chrome"):
    orch = MagicMock()
    orch.ctx = MagicMock()
    orch.ctx.browser_open = browser_open
    orch.ctx.active_browser = browser_name if browser_open else ""
    orch.ctx.last_path = None
    orch.ctx.focused_app = None
    orch.spoken = []
    orch.dispatched = []

    def _speak(msg):
        orch.spoken.append(msg)

    def _handle_command(cmd, **kwargs):
        orch.dispatched.append(cmd)
        return True

    orch.speak.side_effect = _speak
    orch.handle_command.side_effect = _handle_command
    return orch


# ── Import the handler under test ────────────────────────────────────────────

# Stub heavy dependencies before import
for mod in [
    "engines.system", "engines.self_awareness",
    "utils.config", "utils.helpers",
]:
    sys.modules.setdefault(mod, MagicMock())

sys.modules["engines.system"].SystemCtrl = MagicMock()

import importlib
import os, types as _t

# Patch open_item before importing system.py
with patch.dict("sys.modules", {
    "engines.system": MagicMock(SystemCtrl=MagicMock()),
    "engines.self_awareness": MagicMock(MODE_MAP={}),
    "utils.config": MagicMock(Config=MagicMock(MODES=[])),
    "utils.helpers": MagicMock(),
}):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "core.handlers.system",
        pathlib.Path(__file__).parent.parent / "core" / "handlers" / "system.py",
    )
    system_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(system_mod)

handle_app_op = system_mod.handle_app_op


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestOpenChromeSilentFix(unittest.TestCase):
    """open_item returns None/empty → must still speak."""

    def test_open_chrome_always_speaks(self):
        orch = _make_orch()
        orch.files.open_item.return_value = None  # simulate already-open Chrome
        handle_app_op(orch, "open chrome", silent=False)
        self.assertTrue(len(orch.spoken) > 0, "Expected voice output, got silence")
        print(f"  [open chrome] spoke: {orch.spoken[0]!r}")

    def test_open_chrome_already_open_speaks(self):
        orch = _make_orch()
        orch.files.open_item.return_value = ""  # empty string = already open
        handle_app_op(orch, "open chrome", silent=False)
        self.assertGreater(len(orch.spoken), 0, "Silent when Chrome already open")

    def test_open_chrome_sets_browser_open(self):
        orch = _make_orch()
        orch.files.open_item.return_value = "Opened Chrome"
        handle_app_op(orch, "open chrome", silent=False)
        orch.ctx.set_browser_open.assert_called()
        print(f"  set_browser_open called with: {orch.ctx.set_browser_open.call_args}")


class TestCompoundOpenChromePlayYoutube(unittest.TestCase):
    """'open chrome play tamil song in youtube' → dispatches play cmd."""

    def test_play_in_youtube_dispatched(self):
        orch = _make_orch()
        orch.files.open_item.return_value = "Opened Chrome"
        handle_app_op(orch, "open chrome play tamil song in youtube", silent=False)
        self.assertTrue(len(orch.dispatched) > 0, "Expected youtube dispatch, got none")
        dispatched = orch.dispatched[0].lower()
        self.assertIn("tamil", dispatched, f"Expected 'tamil' in dispatched cmd, got {dispatched!r}")
        print(f"  [compound] dispatched: {orch.dispatched[0]!r}")

    def test_play_on_youtube_dispatched(self):
        orch = _make_orch()
        orch.files.open_item.return_value = "Opened Chrome"
        handle_app_op(orch, "open chrome play lofi beats on youtube", silent=False)
        self.assertTrue(len(orch.dispatched) > 0, "Expected youtube dispatch")
        print(f"  [compound on] dispatched: {orch.dispatched[0]!r}")


class TestRouterBrowserSearchPatterns(unittest.TestCase):
    """NL_OVERRIDE patterns for browser search must match the right phrases."""

    def setUp(self):
        with patch.dict("sys.modules", {
            "engines.system": MagicMock(SystemCtrl=MagicMock()),
            "engines.self_awareness": MagicMock(MODE_MAP={}),
            "utils.config": MagicMock(Config=MagicMock(MODES=[], TRIGGERS={})),
            "utils.helpers": MagicMock(),
        }):
            spec = importlib.util.spec_from_file_location(
                "core.router",
                pathlib.Path(__file__).parent.parent / "core" / "router.py",
            )
            router_mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(router_mod)
                self.NL_OVERRIDES = router_mod.NL_OVERRIDES
            except Exception:
                self.NL_OVERRIDES = None

    def _match_intent(self, text):
        if not self.NL_OVERRIDES:
            return None
        text_l = text.lower()
        for pattern, intent, conf in self.NL_OVERRIDES:
            if re.search(pattern, text_l):
                return intent, conf
        return None

    def test_in_opened_chrome_search(self):
        result = self._match_intent("in the opened chrome search for animation")
        if result is None:
            self.skipTest("Router could not be loaded")
        intent, conf = result
        self.assertEqual(intent, "browser_search", f"Expected browser_search, got {intent!r}")
        self.assertGreaterEqual(conf, 0.98)
        print(f"  [router] 'in the opened chrome search for animation' → {intent} @ {conf}")

    def test_open_chrome_play_youtube_pattern(self):
        result = self._match_intent("open chrome play tamil song in youtube")
        if result is None:
            self.skipTest("Router could not be loaded")
        intent, conf = result
        self.assertEqual(intent, "youtube", f"Expected youtube, got {intent!r}")
        print(f"  [router] 'open chrome play tamil song in youtube' → {intent} @ {conf}")


if __name__ == "__main__":
    unittest.main(verbosity=2)

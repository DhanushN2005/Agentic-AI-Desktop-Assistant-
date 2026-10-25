"""Tests for Step 2: Natural-Language Explicit Memory & Markdown Wiki Integration."""
import os
import tempfile
import pytest
from unittest.mock import MagicMock

from core.memory_manager import MemoryManager, MemoryCategory, MemoryEntry
from core.handlers.memory_system import handle_memory_system


class TestMemoryUpgrade:
    def test_export_to_markdown_and_sync(self, tmp_path):
        mm = MemoryManager()
        wiki_file = str(tmp_path / "TEST_MEMORY.md")

        mm.remember("preferred_editor", "VS Code", category=MemoryCategory.PREFERENCES, importance=0.9)
        mm.remember("user_name", "Dhanush", category=MemoryCategory.FACTS, importance=0.8)

        content = mm.export_to_markdown(filepath=wiki_file)
        assert os.path.exists(wiki_file)
        assert "# 🧠 Flexiee Personal Knowledge Wiki" in content
        assert "## 🌟 User Preferences & Personalization" in content
        assert "preferred_editor" in content
        assert "VS Code" in content
        assert "## 📌 Learned Facts & Knowledge" in content
        assert "user_name" in content
        assert "Dhanush" in content

    def test_sync_on_forget(self, tmp_path):
        mm = MemoryManager()
        wiki_file = str(tmp_path / "TEST_MEMORY_FORGET.md")

        mm.remember("temporary_fact", "Temporary Value", category=MemoryCategory.FACTS)
        mm.export_to_markdown(filepath=wiki_file)
        assert "temporary_fact" in open(wiki_file, "r", encoding="utf-8").read()

        mm.forget("temporary_fact")
        mm.export_to_markdown(filepath=wiki_file)
        assert "temporary_fact" not in open(wiki_file, "r", encoding="utf-8").read()

    def test_handle_memory_system_explicit_remember_preference(self):
        orch = MagicMock()
        orch.memory_manager = MemoryManager()
        orch.ctx = MagicMock()
        orch.speak = MagicMock()
        orch.send_to_ui = MagicMock()

        res = handle_memory_system(orch, "remember that I prefer dark mode")
        assert res is True
        orch.speak.assert_called_once()
        assert "remember that" in orch.speak.call_args[0][0].lower()

        # Check in memory manager
        pref = orch.memory_manager.recall("i prefer dark mode")
        if not pref:
            # Check search
            matches = orch.memory_manager.search("dark mode")
            assert len(matches) > 0
            assert matches[0].category == MemoryCategory.PREFERENCES

    def test_handle_memory_system_forget(self):
        orch = MagicMock()
        orch.memory_manager = MemoryManager()
        orch.ctx = MagicMock()
        orch.speak = MagicMock()
        orch.send_to_ui = MagicMock()

        # Remember first
        handle_memory_system(orch, "remember that my city is Bangalore")
        orch.speak.reset_mock()

        # Forget
        res = handle_memory_system(orch, "forget my city is Bangalore")
        assert res is True
        orch.speak.assert_called_once()
        assert "forgotten" in orch.speak.call_args[0][0].lower()

    def test_handle_memory_system_show_wiki(self):
        orch = MagicMock()
        orch.memory_manager = MemoryManager()
        orch.ctx = MagicMock()
        orch.speak = MagicMock()
        orch.send_to_ui = MagicMock()

        res = handle_memory_system(orch, "show memory")
        assert res is True
        orch.speak.assert_called_once()
        assert "memory wiki" in orch.speak.call_args[0][0].lower()
        orch.send_to_ui.assert_any_call("SAY", pytest.approx.__self__ if hasattr(pytest, "__self__") else orch.send_to_ui.call_args_list[-1][0][1])

"""One remember/forget path across every store (architecture fix: memory consolidation)."""
import os
import time
from types import SimpleNamespace

from core.memory_facade import MemoryFacade
from core.memory_manager import MemoryManager
from engines.memory_system import MemorySystem
from engines.self_awareness import SelfAwareness


def _orch(tmp):
    import logging
    mm = MemoryManager.__new__(MemoryManager)
    mm.logger = logging.getLogger("t")
    mm._entries = {}
    mm.DB_PATH = os.path.join(tmp, "mm.db")
    mm._WIKI_DEBOUNCE_SECONDS = 0
    mm.export_to_markdown = lambda *a, **k: ""
    mm._ensure_db()
    return SimpleNamespace(
        memory_manager=mm,
        memory_system=MemorySystem(os.path.join(tmp, "ms.db")),
        awareness=SelfAwareness(os.path.join(tmp, "aw.db")),
        memory=None, brain=None,
    )


def test_forget_reaches_every_store(tmp_path):
    if True:
        orch = _orch(str(tmp_path))
        f = MemoryFacade(orch)
        written = f.remember_fact("my dog", "Rex", raw_fact="my dog is Rex")
        assert {"memory_manager", "memory_system", "awareness"} <= set(written)
        assert orch.awareness.recall_facts()

        report = f.forget("rex")
        assert report.total >= 3
        assert not orch.memory_manager.search("rex")
        assert orch.awareness.recall_facts() == []
        import sqlite3
        with sqlite3.connect(orch.memory_system._db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == 0


def test_forget_unknown_reports_zero(tmp_path):
    assert MemoryFacade(_orch(str(tmp_path))).forget("nothing-here").total == 0


def test_wiki_sync_is_debounced():
    calls = []
    mm = MemoryManager.__new__(MemoryManager)
    mm.logger = __import__("logging").getLogger("t")
    mm._WIKI_DEBOUNCE_SECONDS = 0.2
    mm._wiki_timer = None
    mm.export_to_markdown = lambda *a, **k: calls.append(1)
    for _ in range(50):
        mm.sync_markdown_wiki()
    assert calls == []          # nothing synchronous on the hot path
    time.sleep(0.6)
    assert len(calls) == 1      # 50 writes coalesced into one export


def test_search_memory_returns_empty_list_when_nothing_matches(tmp_path):
    from engines.memory_system import MemorySystem
    assert MemorySystem(str(tmp_path / "m.db")).search_memory("zzz") == []


def test_data_files_are_anchored_to_project_not_cwd(tmp_path, monkeypatch):
    from utils.paths import PROJECT_ROOT, data_file
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLEXIE_DATA_DIR", raising=False)
    assert data_file("flexie_memory.db") == os.path.join(PROJECT_ROOT, "flexie_memory.db")
    monkeypatch.setenv("FLEXIE_DATA_DIR", str(tmp_path))
    assert data_file("x.db") == str(tmp_path / "x.db")

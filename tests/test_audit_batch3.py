"""Batch 3 audit fixes: validator defaults, verify_step, vector backoff, WAL, TTL."""
import sqlite3
import time
from unittest.mock import MagicMock, patch

from verification.capability_validator import CapabilityValidator


# --- 6. capability validator fail-closed ---
def test_validator_unknown_capability_fails():
    v = CapabilityValidator()
    assert v.validate("teleport", "do something", {}) is False


def test_validator_filesystem_unverified_fails():
    v = CapabilityValidator()
    assert v.validate("file", "create a report", {}) is False


def test_validator_filesystem_verified_passes(tmp_path):
    v = CapabilityValidator()
    f = tmp_path / "doc.txt"
    f.write_text("x", encoding="utf-8")
    assert v.validate("file", "create a report", {"active_document": str(f)}) is True


def test_validator_app_no_signal_fails():
    v = CapabilityValidator()
    assert v.validate("application", "open notepad", {}) is False


def test_validator_app_explorer_fails():
    v = CapabilityValidator()
    assert v.validate("application", "open window", {"window_title": "File Explorer"}) is False


def test_validator_clipboard_error_fails():
    v = CapabilityValidator()
    with patch("engines.system.SystemCtrl.get_clipboard", side_effect=OSError("nope")):
        assert v.validate("clipboard", "copy this", {"clipboard": "old"}) is False


# --- 7. verify_step file failure ---
def _fake_orch():
    orch = MagicMock()
    orch.ctx.last_path = None
    orch.ctx.active_document = None
    orch.ctx.last_response = "some long response text"
    orch.logger = MagicMock()
    orch.speak = MagicMock()
    return orch


def test_verify_file_failure_not_verified():
    from core.workflow_executor import WorkflowExecutor
    orch = _fake_orch()
    ex = WorkflowExecutor(orch)
    verified, retries = ex.verify_step("create file report with analysis", {}, "file_save")
    assert verified is False
    assert ex.last_verify_reason is not None and "unverified" in ex.last_verify_reason


def test_verify_file_success_verified(tmp_path):
    from core.workflow_executor import WorkflowExecutor
    orch = _fake_orch()
    f = tmp_path / "out.txt"
    f.write_text("content here", encoding="utf-8")
    orch.ctx.active_document = str(f)
    ex = WorkflowExecutor(orch)
    verified, _ = ex.verify_step("create file report", {}, "file_save")
    assert verified is True
    assert ex.last_verify_reason is None


# --- 8. vector store backoff + queue ---
def _vector_store_no_init():
    from core.vector_store import VectorStore
    vs = VectorStore.__new__(VectorStore)
    vs.logger = MagicMock()
    vs.chroma_client = None
    vs.collection = MagicMock()
    vs.rag_available = True
    vs._consec_errors = 0
    vs._cooldown_until = 0.0
    vs._pending = []
    return vs


def test_search_error_does_not_permanently_disable():
    vs = _vector_store_no_init()
    vs.collection.query.side_effect = RuntimeError("boom")
    assert vs.search_episodes("q") == []
    assert vs.rag_available is True  # still enabled after a single error
    vs.collection.query.side_effect = None
    vs.collection.query.return_value = {"ids": [["a"]], "documents": [["t"]], "metadatas": [[{}]]}
    out = vs.search_episodes("q")
    assert out and out[0]["id"] == "a"


def test_search_cooldown_after_repeated_errors():
    from core.vector_store import VectorStore
    vs = _vector_store_no_init()
    vs.collection.query.side_effect = RuntimeError("boom")
    for _ in range(VectorStore._MAX_CONSEC_ERRORS):
        vs.search_episodes("q")
    n_calls = vs.collection.query.call_count
    vs.search_episodes("q")  # cooldown: no new backend call
    assert vs.collection.query.call_count == n_calls


def test_add_episode_queues_on_error():
    vs = _vector_store_no_init()
    vs.collection.add.side_effect = RuntimeError("boom")
    vs.add_episode("d1", "hello world", {})
    assert len(vs._pending) == 1
    vs.collection.add.side_effect = None
    vs._flush_pending()
    assert vs._pending == []


# --- 9. memory manager WAL + single-row ---
def test_memory_wal_and_single_row(tmp_path, monkeypatch):
    from core.memory_manager import MemoryManager, MemoryCategory
    db = tmp_path / "mem.db"
    monkeypatch.setattr(MemoryManager, "DB_PATH", str(db))
    mm = MemoryManager()
    mode = sqlite3.connect(str(db)).execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"
    mm.remember("k1", "v1", MemoryCategory.FACTS)
    mm.remember("k2", "v2", MemoryCategory.FACTS)
    with sqlite3.connect(str(db)) as conn:
        n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert n == 2
    assert mm.recall("k1").value == "v1"
    assert mm.forget("k1") is True
    with sqlite3.connect(str(db)) as conn:
        n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert n == 1
    assert mm.cleanup_expired() == 0


# --- 10. brain maintenance thread ---
def test_brain_no_cleanup_in_read_path():
    import pathlib
    src = pathlib.Path("core/brain.py").read_text(encoding="utf-8")
    assert "hash(prompt) % 20" not in src


def test_brain_maintenance_thread_runs_cleanup():
    from core.brain import Brain
    b = Brain.__new__(Brain)
    b._cache = {}
    b._cache_max = 64
    b.memory_manager = MagicMock()
    assert b.ensure_maintenance_thread(interval_seconds=0.05) is True
    time.sleep(0.3)
    assert b.memory_manager.cleanup_expired.call_count >= 1
    # idempotent
    assert b.ensure_maintenance_thread() is True


# --- 11. permission TTL + empty classify ---
def test_classify_empty_fails_closed():
    from core.permission_system import PermissionSystem
    from core.tool_registry import PermissionLevel
    ps = PermissionSystem()
    assert ps.classify_action("") == PermissionLevel.USER_CONFIRMATION
    assert ps.classify_action("   ") == PermissionLevel.USER_CONFIRMATION
    assert ps.requires_confirmation("") is True


def test_escalate_auto_resets():
    from core.permission_system import PermissionSystem
    from core.tool_registry import PermissionLevel
    ps = PermissionSystem()
    ps.escalate(PermissionLevel.DANGEROUS, ttl_seconds=0.05)
    assert ps.current_level == PermissionLevel.DANGEROUS
    time.sleep(0.1)
    ps.check_permission("search for cats")
    assert ps.current_level == PermissionLevel.READ_ONLY


def test_escalate_no_expiry_with_zero_ttl():
    from core.permission_system import PermissionSystem
    from core.tool_registry import PermissionLevel
    ps = PermissionSystem()
    ps.escalate(PermissionLevel.DANGEROUS, ttl_seconds=0)
    time.sleep(0.05)
    ps.check_permission("search for cats")
    assert ps.current_level == PermissionLevel.DANGEROUS
    ps.reset()
    assert ps.current_level == PermissionLevel.READ_ONLY

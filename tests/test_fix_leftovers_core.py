"""Regression tests for the leftover core fixes (UT-33, MM-8, MM-10, MM-16, EN-6, RT-8)."""
import logging
import queue
import sqlite3
import threading
from types import SimpleNamespace

from core.brain import Brain
from core.memory_manager import MemoryCategory
from core.orchestrator import FlexieOrchestrator
from engines.memory import MemoryEngine
from utils.config import Config


def _engine(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DB_NAME", str(tmp_path / "m.db"))
    monkeypatch.setattr(Config, "LOG_FILE", str(tmp_path / "a.log"))
    return MemoryEngine()


# ------------------------------------------------------------------ UT-33
def test_identical_reminders_have_unique_ids_and_fire_independently(tmp_path, monkeypatch):
    me = _engine(tmp_path, monkeypatch)
    a = me.add_reminder("call mom", -1)
    b = me.add_reminder("call mom", -1)
    c = me.add_reminder("call mom", 60)
    assert len({a, b, c}) == 3
    assert me.mark_reminder_done(a) == 1
    # only the one marked is done: b is still due, c still pending
    assert me.due_reminder_items() == [(b, "call mom")]
    assert me.due_reminder_items() == []
    assert me.list_reminders() == ["call mom"]  # c remains


def test_mark_reminder_done_by_task_marks_only_one(tmp_path, monkeypatch):
    me = _engine(tmp_path, monkeypatch)
    me.add_reminder("x", 10)
    me.add_reminder("x", 20)
    assert me.mark_reminder_done("x") == 1
    assert me.list_reminders() == ["x"]


def test_legacy_reminders_table_without_id_column_works(tmp_path, monkeypatch):
    db = str(tmp_path / "legacy.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE reminders (task TEXT, trigger_ts REAL, done INTEGER DEFAULT 0)")
    con.execute("INSERT INTO reminders(task,trigger_ts) VALUES('old',1)")
    con.execute("INSERT INTO reminders(task,trigger_ts) VALUES('old',1)")
    con.commit()
    con.close()
    monkeypatch.setattr(Config, "DB_NAME", db)
    monkeypatch.setattr(Config, "LOG_FILE", str(tmp_path / "a.log"))
    me = MemoryEngine()
    items = me.due_reminder_items()
    assert [t for _i, t in items] == ["old", "old"] and items[0][0] != items[1][0]
    assert me.add_reminder("new", -1) > 0


def test_reminder_loop_fires_each_identical_reminder(tmp_path, monkeypatch):
    me = _engine(tmp_path, monkeypatch)
    me.add_reminder("t", -1)
    me.add_reminder("t", -1)
    spoken = []
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.memory, o.is_processing = me, False
    o.speak = lambda text, **k: spoken.append(text)

    class Stop(Exception):
        pass

    def _stop(_s):
        raise Stop()
    import core.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod.time, "sleep", _stop)
    try:
        o._reminder_loop()
    except Stop:
        pass
    assert spoken == ["Reminder: t", "Reminder: t"]
    assert me.due_reminder_items() == []


# ------------------------------------------------------------------ MM-8
def test_assistant_replies_not_stored_as_conversation_memory(tmp_path, monkeypatch):
    me = _engine(tmp_path, monkeypatch)
    remembered = []
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.memory = me
    o.memory_manager = SimpleNamespace(remember=lambda *a, **k: remembered.append(a))
    o.record_response("here is my long reply")
    assert remembered == []
    assert me.get_conversation_messages(limit=5, max_chars=1000)[-1]["role"] == "assistant"


def test_prune_stores_calls_every_prune_and_survives_failures():
    calls = []

    def rec(n, boom=False):
        def f(*a, **k):
            calls.append(n)
            if boom:
                raise RuntimeError("x")
        return f
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.memory = SimpleNamespace(prune=rec("memory", boom=True))
    o.memory_system = SimpleNamespace(prune=rec("memory_system"))
    o.awareness = SimpleNamespace(prune=rec("awareness"))
    o.memory_manager = SimpleNamespace(cleanup_expired=rec("mm"))
    o.brain = SimpleNamespace(vector_store=SimpleNamespace(prune_older_than=rec("vs")))
    o._prune_stores()
    assert calls == ["memory", "memory_system", "awareness", "mm", "vs"]


def test_maintenance_tick_runs_tasks_at_most_hourly():
    b = Brain.__new__(Brain)
    ran, cleaned = [], []
    b.memory_manager = SimpleNamespace(cleanup_expired=lambda: cleaned.append(1))
    b.add_maintenance_task(lambda: ran.append(1), every_seconds=3600)
    b._run_maintenance_once(now=100.0)
    b._run_maintenance_once(now=1900.0)   # 30 min later: cleanup again, task not yet
    assert (len(cleaned), len(ran)) == (2, 1)
    b._run_maintenance_once(now=4000.0)
    assert len(ran) == 2


# ------------------------------------------------------------------ MM-10
def test_brain_passes_memory_entries_to_compiler():
    seen = {}

    class Stop(Exception):
        pass

    class Comp:
        def compile(self, sp, ctx):
            seen.update(ctx)
            raise Stop()
    hit = SimpleNamespace(key="k", value="v", category=MemoryCategory.CONVERSATION)
    b = Brain.__new__(Brain)
    b.context_compiler = Comp()
    b.vector_store = SimpleNamespace(rag_available=True, search_episodes=lambda q, limit=5: [])
    b.memory_manager = SimpleNamespace(search=lambda *a, **k: [hit])
    b.system_prompt = "sys"
    try:
        b._ask_impl("hi", None, None, False, True)
    except Exception:
        pass  # compile raising is swallowed by brain; later provider calls are irrelevant
    assert seen.get("memory_entries") == [hit]


def test_compiler_drops_conversation_entries_from_brain_style_input():
    from context.compiler import ContextCompiler
    conv = SimpleNamespace(key="c", value="CONVO", category=MemoryCategory.CONVERSATION)
    fact = SimpleNamespace(key="f", value="FACT", category=MemoryCategory.FACTS)
    out = ContextCompiler().compile("sys", {"memory": "", "memory_entries": [conv, fact]})
    assert "FACT" in out and "CONVO" not in out


# ------------------------------------------------------------------ MM-16
def test_memory_agent_reuses_one_vector_store(monkeypatch):
    import agents.memory_agent as ma
    import core.vector_store as vs
    made = []

    class FakeVS:
        def __init__(self):
            made.append(1)

        def add_episode(self, q, v):
            pass
    monkeypatch.setattr(vs, "VectorStore", FakeVS)
    monkeypatch.setattr(ma, "_STORE", None)
    agent = ma.MemoryAgent()
    for _ in range(3):
        agent.execute_task({"action": "store_episodic", "query": "q", "value": "v"})
    assert len(made) == 1
    monkeypatch.setattr(ma, "_STORE", None)


# ------------------------------------------------------------------ EN-6
def test_knowledge_uses_shared_exclusion_rules():
    import engines.knowledge as k
    import utils.name_index as ni
    assert k.is_excluded_component is ni.is_excluded_component


# ------------------------------------------------------------------ RT-8
def _worker_orch():
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.cmd_queue = queue.Queue()
    o.stop_event = threading.Event()
    o.is_processing = False
    o.logger = logging.getLogger("t")
    o.handle_command = lambda cmd: True
    return o


def test_empty_blocking_command_releases_waiter_and_balances_queue():
    o = _worker_orch()
    ev, holder = threading.Event(), []
    o.cmd_queue.put(("", ev, holder))
    o._process_queue_item(o.cmd_queue.get())
    assert ev.is_set() and holder
    assert o.cmd_queue.unfinished_tasks == 0


def test_malformed_queue_item_still_balances_task_done():
    o = _worker_orch()
    o.cmd_queue.put(("only", "two"))
    try:
        o._process_queue_item(o.cmd_queue.get())
    except ValueError:
        pass
    assert o.cmd_queue.unfinished_tasks == 0


def test_normal_command_runs_and_signals():
    o = _worker_orch()
    ev, holder = threading.Event(), []
    o.cmd_queue.put(("hello", ev, holder))
    o._process_queue_item(o.cmd_queue.get())
    assert ev.is_set() and holder[0].success and o.is_processing is False


def test_cleanup_closes_email_and_isolates_failures():
    closed = []

    def boom():
        raise RuntimeError("boom")
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.logger = logging.getLogger("t")
    o.mcp_manager = SimpleNamespace(shutdown=boom)
    o.browser = SimpleNamespace(cleanup=lambda: closed.append("browser"))
    o.email = SimpleNamespace(close=lambda: closed.append("email"))
    o.voice = SimpleNamespace(stop_speech=False)
    o.cleanup()
    assert closed == ["browser", "email"] and o.voice.stop_speech is True


def test_speech_worker_balances_task_done_when_tts_raises():
    o = FlexieOrchestrator.__new__(FlexieOrchestrator)
    o.logger = logging.getLogger("t")
    o._speech_queue = queue.Queue()
    o._speech_queue.put("hi")
    calls = {"n": 0}

    def speak(text):
        calls["n"] += 1
        raise RuntimeError("tts")
    o.voice = SimpleNamespace(speak=speak)
    real_get = o._speech_queue.get

    def get(timeout=1):
        if calls["n"]:
            raise SystemExit
        return real_get(timeout=timeout)
    o._speech_queue.get = get
    try:
        o._speech_worker_loop()
    except SystemExit:
        pass
    assert o._speech_queue.unfinished_tasks == 0

import datetime
import json
import logging
import os
import threading
import time

from core.memory_manager import scrub
from utils.config import Config
from utils.paths import data_file
from utils.sql_like import like_contains
from utils.sqlite_util import fast_connect

logger = logging.getLogger("Flexie.MemoryEngine")


class MemoryEngine:
    def __init__(self):
        # Shared WAL connection (auto-commit per statement, ~0.1 ms/write) instead of a
        # private rollback-journal connection (~13 ms/write on Windows).
        self.conn   = fast_connect(Config.DB_NAME)
        self._lock  = threading.Lock()
        self._log_lock = threading.Lock()
        self._init()

    def _init(self):
        with self._lock:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS memory (
                    key TEXT PRIMARY KEY, value TEXT, category TEXT DEFAULT 'general');
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, cmd TEXT, ts TEXT);
                CREATE TABLE IF NOT EXISTS routines (name TEXT PRIMARY KEY, steps TEXT);
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT, trigger_ts REAL, done INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT, content TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT, content TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                CREATE INDEX IF NOT EXISTS idx_chat_history_ts ON chat_history(ts);
                CREATE INDEX IF NOT EXISTS idx_conversation_turns_ts ON conversation_turns(ts);
                CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);
            """)

    def store(self, key, value, cat="general"):
        key, value = scrub(key), scrub(value)
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO memory VALUES(?,?,?)", (key, value, cat))

    def recall(self, key):
        with self._lock:
            r = self.conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
            return r[0] if r else None

    def category_facts(self, cat):
        with self._lock:
            return self.conn.execute("SELECT key,value FROM memory WHERE category=?", (cat,)).fetchall()

    def all_facts(self):
        with self._lock:
            return self.conn.execute("SELECT key,value,category FROM memory").fetchall()

    def forget(self, key):
        with self._lock:
            self.conn.execute("DELETE FROM memory WHERE key=?", (key,))

    # ----------------------------------------------------------------- log file --
    def _log_path(self) -> str:
        return data_file(Config.LOG_FILE)

    def _forget_log_lines(self, text: str) -> int:
        """Remove activity-log lines containing ``text`` (atomic rewrite). Returns lines removed."""
        path = self._log_path()
        needle = (text or "").lower()
        if not needle:
            return 0
        with self._log_lock:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except OSError:
                return 0
            kept = [ln for ln in lines if needle not in ln.lower()]
            removed = len(lines) - len(kept)
            if removed:
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.writelines(kept)
                os.replace(tmp, path)
            return removed

    def forget_everywhere(self, text: str) -> dict[str, int]:
        """Delete ``text`` from facts, chat history, turns, activity and the activity log.

        Saved ``ctx_last_response`` / ``ctx_last_query`` rows live in the facts table and
        are matched by value. Returns removed counts per table.
        """
        pat = like_contains(text)
        counts: dict[str, int] = {}
        with self._lock:
            with self.conn as c:
                counts["memory"] = c.execute(
                    "DELETE FROM memory WHERE key LIKE ? ESCAPE '!' OR value LIKE ? ESCAPE '!'",
                    (pat, pat)).rowcount
                counts["chat_history"] = c.execute(
                    "DELETE FROM chat_history WHERE content LIKE ? ESCAPE '!'", (pat,)).rowcount
                counts["conversation_turns"] = c.execute(
                    "DELETE FROM conversation_turns WHERE content LIKE ? ESCAPE '!'", (pat,)).rowcount
                counts["activity"] = c.execute(
                    "DELETE FROM activity WHERE cmd LIKE ? ESCAPE '!'", (pat,)).rowcount
        try:
            counts["activity_log"] = self._forget_log_lines(text)
        except Exception as e:  # noqa: BLE001
            logger.warning("activity log forget failed: %s", e)
        return {k: v for k, v in counts.items() if v and v > 0}

    def forget_matching(self, text: str) -> int:
        """Delete stored facts/history containing ``text``. Returns rows removed."""
        return sum(self.forget_everywhere(text).values())

    def log_activity(self, cmd):
        cmd = scrub(cmd)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.conn.execute("INSERT INTO activity(cmd,ts) VALUES(?,?)", (cmd, ts))
        # Optional persistent file log: anchored path, UTF-8, never raises.
        try:
            with self._log_lock, open(self._log_path(), "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {cmd}\n")
        except Exception as e:  # noqa: BLE001
            logger.warning("activity log write failed: %s", e)

    def recent_activity(self, n=5):
        with self._lock:
            return self.conn.execute(
                "SELECT cmd,ts FROM activity ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def save_routine(self, name, steps):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO routines VALUES(?,?)", (name, json.dumps(steps)))

    def get_routine(self, name):
        with self._lock:
            r = self.conn.execute("SELECT steps FROM routines WHERE name=?", (name,)).fetchone()
            return json.loads(r[0]) if r else None

    def list_reminders(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT task FROM reminders WHERE done=0 ORDER BY trigger_ts ASC"
            ).fetchall()
        return [r[0] for r in rows]

    def add_reminder(self, task, minutes) -> int:
        """Store a reminder; returns its unique id (rowid, valid for legacy tables too)."""
        t = time.time() + minutes * 60
        with self._lock:
            cur = self.conn.execute("INSERT INTO reminders(task,trigger_ts) VALUES(?,?)", (task, t))
            return int(cur.lastrowid)

    def due_reminder_items(self) -> list[tuple[int, str]]:
        """Claim due reminders as (id, task); each is marked done individually by rowid."""
        now = time.time()
        with self._lock:
            with self.conn as c:
                rows = c.execute(
                    "SELECT rowid,task FROM reminders WHERE done=0 AND trigger_ts<=? ORDER BY trigger_ts",
                    (now,)).fetchall()
                for rid, _task in rows:
                    c.execute("UPDATE reminders SET done=1 WHERE rowid=?", (rid,))
        return [(int(r[0]), r[1]) for r in rows]

    def due_reminders(self):
        return [task for _rid, task in self.due_reminder_items()]

    def mark_reminder_done(self, task) -> int:
        """Mark ONE reminder done: by id (int) or, for a task string, the earliest pending match."""
        with self._lock:
            if isinstance(task, int) and not isinstance(task, bool):
                return self.conn.execute(
                    "UPDATE reminders SET done=1 WHERE rowid=? AND done=0", (task,)).rowcount
            return self.conn.execute(
                "UPDATE reminders SET done=1 WHERE rowid=("
                "SELECT rowid FROM reminders WHERE task=? AND done=0 ORDER BY trigger_ts, rowid LIMIT 1)",
                (task,)).rowcount

    def set_setting(self, k, v):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v)))

    def get_setting(self, k, default):
        with self._lock:
            r = self.conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
            return r[0] if r else default

    def add_chat(self, role, content):
        content = scrub(content)
        with self._lock:
            self.conn.execute("INSERT INTO chat_history(role, content) VALUES(?,?)", (role, content))

    def get_context(self, limit=10) -> str:
        with self._lock:
            rows = self.conn.execute(
                "SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        context = [f"{r[0]}: {r[1]}" for r in reversed(rows)]
        return "\n".join(context)

    def add_conversation_turn(self, role, content):
        if role not in {"user", "assistant"} or not content:
            return
        content = scrub(content)
        with self._lock:
            self.conn.execute("INSERT INTO conversation_turns(role, content) VALUES(?,?)", (role, content))

    def get_conversation_messages(self, limit=None, max_chars=None):
        if limit is None:
            limit = Config.CONVERSATION_HISTORY_TURNS
        if max_chars is None:
            max_chars = Config.CONVERSATION_HISTORY_CHARS
        with self._lock:
            rows = self.conn.execute(
                "SELECT role, content FROM conversation_turns ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

        messages = [
            {"role": role, "content": str(content)}
            for role, content in reversed(rows)
            if role in {"user", "assistant"} and content
        ]
        while messages and sum(len(item["content"]) for item in messages) > max_chars:
            messages.pop(0)
        return messages

    # ---------------------------------------------------------------- retention --
    def prune(self, max_chat: int = 2000, max_turns: int = 2000, max_activity: int = 5000,
              max_log_lines: int = 5000) -> dict[str, int]:
        """Delete the oldest rows beyond the caps (call from the maintenance thread)."""
        out: dict[str, int] = {}
        with self._lock:
            with self.conn as c:
                for table, cap in (("chat_history", max_chat), ("conversation_turns", max_turns),
                                   ("activity", max_activity)):
                    out[table] = c.execute(
                        f"DELETE FROM {table} WHERE id <= "
                        f"(SELECT id FROM {table} ORDER BY id DESC LIMIT 1 OFFSET ?)", (max(0, cap),)
                    ).rowcount
        try:
            with self._log_lock:
                path = self._log_path()
                with open(path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                if len(lines) > max_log_lines:
                    tmp = f"{path}.{os.getpid()}.tmp"
                    with open(tmp, "w", encoding="utf-8", newline="") as f:
                        f.writelines(lines[-max_log_lines:])
                    os.replace(tmp, path)
                    out["activity_log"] = len(lines) - max_log_lines
        except OSError:
            pass
        return {k: v for k, v in out.items() if v and v > 0}

import sqlite3
import threading
import datetime
import json
import time
from utils.config import Config

class MemoryEngine:
    def __init__(self):
        self.conn   = sqlite3.connect(Config.DB_NAME, check_same_thread=False)
        self._lock  = threading.Lock()
        self._init()

    def _init(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.executescript("""
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
            """)
            self.conn.commit()

    def store(self, key, value, cat="general"):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR REPLACE INTO memory VALUES(?,?,?)", (key, value, cat))
            self.conn.commit()

    def recall(self, key):
        with self._lock:
            cur = self.conn.cursor()
            r = cur.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
            return r[0] if r else None

    def category_facts(self, cat):
        with self._lock:
            cur = self.conn.cursor()
            return cur.execute("SELECT key,value FROM memory WHERE category=?", (cat,)).fetchall()

    def all_facts(self):
        with self._lock:
            cur = self.conn.cursor()
            return cur.execute("SELECT key,value,category FROM memory").fetchall()

    def forget(self, key):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM memory WHERE key=?", (key,)); self.conn.commit()

    def log_activity(self, cmd):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO activity(cmd,ts) VALUES(?,?)", (cmd, ts))
            self.conn.commit()
        # Optional: persistent file log
        with open(Config.LOG_FILE, "a") as f:
            f.write(f"[{ts}] {cmd}\n")

    def recent_activity(self, n=5):
        with self._lock:
            cur = self.conn.cursor()
            return cur.execute(
                "SELECT cmd,ts FROM activity ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def save_routine(self, name, steps):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR REPLACE INTO routines VALUES(?,?)", (name, json.dumps(steps)))
            self.conn.commit()

    def get_routine(self, name):
        with self._lock:
            cur = self.conn.cursor()
            r = cur.execute("SELECT steps FROM routines WHERE name=?", (name,)).fetchone()
            return json.loads(r[0]) if r else None

    def list_reminders(self):
        with self._lock:
            cur = self.conn.cursor()
            rows = cur.execute(
                "SELECT task FROM reminders WHERE done=0 ORDER BY trigger_ts ASC"
            ).fetchall()
        return [r[0] for r in rows]

    def add_reminder(self, task, minutes):
        t = time.time() + minutes * 60
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO reminders(task,trigger_ts) VALUES(?,?)", (task, t))
            self.conn.commit()

    def due_reminders(self):
        now = time.time()
        with self._lock:
            cur = self.conn.cursor()
            rows = cur.execute(
                "SELECT id,task FROM reminders WHERE done=0 AND trigger_ts<=?", (now,)).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                cur.execute(f"UPDATE reminders SET done=1 WHERE id IN ({','.join('?'*len(ids))})", ids)
                self.conn.commit()
        return [r[1] for r in rows]

    def mark_reminder_done(self, task: str):
        """Mark a specific reminder as done."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("UPDATE reminders SET done=1 WHERE task=? AND done=0", (task,))
            self.conn.commit()

    def set_setting(self, k, v):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v))); self.conn.commit()

    def get_setting(self, k, default):
        with self._lock:
            cur = self.conn.cursor()
            r = cur.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
            return r[0] if r else default

    def add_chat(self, role, content):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO chat_history(role, content) VALUES(?,?)", (role, content))
            self.conn.commit()

    def get_context(self, limit=10) -> str:
        with self._lock:
            cur = self.conn.cursor()
            rows = cur.execute(
                "SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            # Reverse to maintain chronological order
            context = [f"{r[0]}: {r[1]}" for r in reversed(rows)]
            return "\n".join(context)

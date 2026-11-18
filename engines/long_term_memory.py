import sqlite3
import threading

from core.memory_manager import scrub
from utils.paths import data_file
from utils.sql_like import like_contains


class GlobalMemory:
    """Sidecar module for Long-Term User Profiling (Production Tier)."""
    def __init__(self):
        self.db_path = data_file("flexie_global_profile.db")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile (
                    key TEXT PRIMARY KEY, value TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            """)
            conn.commit()
            conn.close()

    def set_preference(self, key: str, value: str):
        key, value = scrub(key), scrub(value)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("INSERT OR REPLACE INTO profile(key, value) VALUES(?,?)", (key, value))
            conn.commit()
            conn.close()

    def forget_matching(self, text: str) -> int:
        """Delete profile rows whose key or value contains ``text``. Returns rows removed."""
        pat = like_contains(text)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    "DELETE FROM profile WHERE key LIKE ? ESCAPE '!' OR value LIKE ? ESCAPE '!'", (pat, pat))
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def get_preference(self, key: str, default=None):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            res = conn.execute("SELECT value FROM profile WHERE key=?", (key,)).fetchone()
            conn.close()
            return res[0] if res else default

    def learn_from_history(self, recent_chats: str):
        """Analyzes chat history to infer user preferences (Heuristic)."""
        # Simple extraction for dark/light mode preference as an example
        if "dark mode" in recent_chats.lower():
            self.set_preference("ui_theme", "dark")
        elif "light mode" in recent_chats.lower():
            self.set_preference("ui_theme", "light")

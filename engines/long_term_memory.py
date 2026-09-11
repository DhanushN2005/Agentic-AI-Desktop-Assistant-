import sqlite3
import threading
import json
import os

class GlobalMemory:
    """Sidecar module for Long-Term User Profiling (Production Tier)."""
    def __init__(self):
        self.db_path = "flexie_global_profile.db"
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
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("INSERT OR REPLACE INTO profile(key, value) VALUES(?,?)", (key, value))
            conn.commit()
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

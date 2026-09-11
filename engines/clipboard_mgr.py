import time
import sqlite3
import threading
from typing import List, Optional

try:
    import pyperclip
    _CLIP_OK = True
except ImportError:
    _CLIP_OK = False


class ClipboardManagerEngine:
    """Clipboard history manager using SQLite."""

    def __init__(self, db_path: str = "clipboard_history.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._last_content = ""
        self._init_db()
        self._start_monitor()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clipboard (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    pinned INTEGER DEFAULT 0,
                    timestamp REAL DEFAULT (strftime('%s','now'))
                )
            """)
            conn.commit()
            conn.close()

    def _start_monitor(self):
        def _monitor():
            while True:
                try:
                    if _CLIP_OK:
                        current = pyperclip.paste()
                        if current and current != self._last_content and len(current.strip()) > 0:
                            self._last_content = current
                            self._add(current)
                except Exception:
                    pass
                time.sleep(2)
        t = threading.Thread(target=_monitor, daemon=True)
        t.start()

    def _add(self, content: str):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("INSERT INTO clipboard (content) VALUES (?)", (content[:5000],))
            conn.commit()
            conn.close()

    def copy(self, text: str) -> str:
        if _CLIP_OK:
            pyperclip.copy(text)
        self._add(text)
        return f"Copied to clipboard."

    def paste(self) -> str:
        if _CLIP_OK:
            return pyperclip.paste()
        return "Clipboard not available."

    def history(self, limit: int = 10) -> str:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT content, pinned FROM clipboard ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
        if not rows:
            return "Clipboard history is empty."
        lines = []
        for i, (content, pinned) in enumerate(rows):
            pin = " [PINNED]" if pinned else ""
            short = content[:60].replace("\n", " ") + ("..." if len(content) > 60 else "")
            lines.append(f"{i+1}. {short}{pin}")
        return "Clipboard history:\n" + "\n".join(lines)

    def pin(self, index: int) -> str:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("UPDATE clipboard SET pinned = 1 WHERE id = ?", (index,))
            conn.commit()
            conn.close()
        return f"Item {index} pinned."

    def search(self, query: str) -> str:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT content FROM clipboard WHERE content LIKE ? ORDER BY id DESC LIMIT 5",
                (f"%{query}%",)
            ).fetchall()
            conn.close()
        if not rows:
            return f"No clipboard items matching '{query}'."
        lines = [f"{i+1}. {r[0][:80]}" for i, r in enumerate(rows)]
        return "Search results:\n" + "\n".join(lines)

    def clear(self) -> str:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM clipboard WHERE pinned = 0")
            conn.commit()
            conn.close()
        return "Clipboard history cleared (pinned items kept)."

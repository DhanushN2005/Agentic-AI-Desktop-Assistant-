import logging
import os
import re
import sqlite3
import threading
import time

from utils.paths import data_file

try:
    import pyperclip
    _CLIP_OK = True
except ImportError as _e:
    logging.debug("[engines/clipboard_mgr.py:9] Swallowed exception: %s: %s", type(_e).__name__, _e)
    _CLIP_OK = False

MAX_ROWS = 200            # unpinned history rows kept
TTL_SECONDS = 24 * 3600   # unpinned rows older than this are dropped

_SECRET_WORDS = re.compile(r"pass(?:word|wd|code)|secret|api[\s_-]?key|private[\s_-]?key|\btoken\b|\bpin\b|\bcvv\b", re.I)
_TOKEN_PREFIX = re.compile(r"^(?:sk-|ghp_|gho_|github_pat_|xox[bap]-|AKIA|AIza|eyJ|ya29\.|-----BEGIN)")
_TOKEN_CHARS = re.compile(r"^[A-Za-z0-9+/_\-=.]{20,}$")


def looks_like_secret(text: str) -> bool:
    """Heuristic: passwords, OTPs, card numbers and long random tokens are never stored."""
    t = (text or "").strip()
    if not t:
        return False
    if _SECRET_WORDS.search(t):
        return True
    if re.fullmatch(r"\d{4,8}", t):                       # OTP / PIN
        return True
    if re.fullmatch(r"(?:\d[ -]?){13,19}", t):            # card-like number
        return True
    if _TOKEN_PREFIX.match(t):
        return True
    if _TOKEN_CHARS.match(t) and re.search(r"\d", t) and re.search(r"[A-Za-z]", t):
        return True                                       # long random-looking token
    return False


def _clipboard_flagged_private() -> bool:
    """True if the copying app asked Windows to keep this out of history/monitors."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        u32 = ctypes.windll.user32
        u32.RegisterClipboardFormatW.restype = ctypes.c_uint
        exclude = u32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
        if exclude and u32.IsClipboardFormatAvailable(exclude):
            return True
        can_include = u32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
        if can_include and u32.IsClipboardFormatAvailable(can_include):
            u32.OpenClipboard.argtypes = [ctypes.c_void_p]
            u32.GetClipboardData.restype = ctypes.c_void_p
            k32 = ctypes.windll.kernel32
            k32.GlobalLock.restype = ctypes.c_void_p
            k32.GlobalLock.argtypes = [ctypes.c_void_p]
            k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            if u32.OpenClipboard(None):
                try:
                    h = u32.GetClipboardData(can_include)
                    if h:
                        ptr = k32.GlobalLock(h)
                        if ptr:
                            try:
                                return ctypes.c_uint32.from_address(ptr).value == 0
                            finally:
                                k32.GlobalUnlock(h)
                finally:
                    u32.CloseClipboard()
    except Exception as _e:
        logging.debug("clipboard privacy-format probe failed: %s", _e)
    return False


def monitor_enabled_by_setting() -> bool:
    """Monitoring is OPT-IN: Config.CLIPBOARD_MONITOR or FLEXIE_CLIPBOARD_MONITOR=1."""
    try:
        from utils.config import Config
        if getattr(Config, "CLIPBOARD_MONITOR", False):
            return True
    except Exception as _e:
        logging.debug("clipboard monitor setting unavailable: %s", _e)
    return os.environ.get("FLEXIE_CLIPBOARD_MONITOR", "").strip().lower() in ("1", "true", "yes", "on")


class ClipboardManagerEngine:
    """Clipboard history manager using SQLite (opt-in monitor, capped, expiring, secret-aware)."""

    def __init__(self, db_path: str | None = None, monitor: bool | None = None,
                 clock=time.time, max_rows: int = MAX_ROWS, ttl: float = TTL_SECONDS):
        self._db_path = db_path or data_file("clipboard_history.db")
        self._lock = threading.Lock()
        self._last_content = ""
        self._clock = clock
        self.max_rows = max_rows
        self.ttl = ttl
        self._view_ids: list[int] = []     # row ids in the order last shown to the user
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._init_db()
        self._prune()
        if monitor is None:
            monitor = monitor_enabled_by_setting()
        if monitor:
            self.start_monitoring()

    # ------------------------------------------------------------------ db
    def _connect(self):
        return sqlite3.connect(self._db_path)

    def _init_db(self):
        with self._lock:
            conn = self._connect()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clipboard (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    pinned INTEGER DEFAULT 0,
                    timestamp REAL DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()

    def _prune(self):
        """Drop expired unpinned rows and cap the unpinned row count."""
        cutoff = self._clock() - self.ttl
        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM clipboard WHERE pinned = 0 AND timestamp < ?", (cutoff,))
            conn.execute(
                "DELETE FROM clipboard WHERE pinned = 0 AND id NOT IN "
                "(SELECT id FROM clipboard WHERE pinned = 0 ORDER BY id DESC LIMIT ?)",
                (self.max_rows,),
            )
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------ monitor (opt-in)
    @property
    def monitoring(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start_monitoring(self) -> str:
        if self.monitoring:
            return "Clipboard history is already on."
        self._stop.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="clipboard-monitor")
        self._thread.start()
        return "Clipboard history is on. Passwords, codes and tokens are never saved."

    def stop_monitoring(self) -> str:
        self._stop.set()
        return "Clipboard history is off."

    def _poll_once(self):
        if not _CLIP_OK:
            return
        current = pyperclip.paste()
        if current and current != self._last_content and current.strip():
            self._last_content = current
            if _clipboard_flagged_private():
                return
            self._add(current)

    def _monitor_loop(self):
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as _e:
                logging.debug("clipboard poll failed: %s: %s", type(_e).__name__, _e)
            self._stop.wait(2)

    # ------------------------------------------------------------------ api
    def _add(self, content: str) -> bool:
        if looks_like_secret(content):
            return False
        with self._lock:
            conn = self._connect()
            conn.execute("INSERT INTO clipboard (content, timestamp) VALUES (?, ?)",
                         (content[:5000], self._clock()))
            conn.commit()
            conn.close()
        self._prune()
        return True

    def copy(self, text: str) -> str:
        if _CLIP_OK:
            pyperclip.copy(text)
        self._add(text)
        return "Copied to clipboard."

    def paste(self) -> str:
        if _CLIP_OK:
            return pyperclip.paste()
        return "Clipboard not available."

    def history(self, limit: int = 10) -> str:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, content, pinned FROM clipboard ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
        self._view_ids = [r[0] for r in rows]
        if not rows:
            return "Clipboard history is empty." if self.monitoring or monitor_enabled_by_setting() else (
                "Clipboard history is empty (automatic monitoring is off; it is opt-in)."
            )
        lines = []
        for i, (_rid, content, pinned) in enumerate(rows):
            pin = " [PINNED]" if pinned else ""
            short = content[:60].replace("\n", " ") + ("..." if len(content) > 60 else "")
            lines.append(f"{i+1}. {short}{pin}")
        return "Clipboard history:\n" + "\n".join(lines)

    def pin(self, index: int) -> str:
        """Pin the item shown at 1-based display position ``index`` (EN-20)."""
        if not self._view_ids:
            self.history()
        try:
            pos = int(index)
        except (TypeError, ValueError):
            return "Which item number should I pin?"
        if not 1 <= pos <= len(self._view_ids):
            return f"There is no item {index} in the clipboard history."
        row_id = self._view_ids[pos - 1]
        with self._lock:
            conn = self._connect()
            conn.execute("UPDATE clipboard SET pinned = 1 WHERE id = ?", (row_id,))
            conn.commit()
            conn.close()
        return f"Item {pos} pinned."

    def search(self, query: str) -> str:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, content FROM clipboard WHERE content LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 5",
                ("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)
            ).fetchall()
            conn.close()
        if not rows:
            return f"No clipboard items matching '{query}'."
        self._view_ids = [r[0] for r in rows]
        lines = [f"{i+1}. {r[1][:80]}" for i, r in enumerate(rows)]
        return "Search results:\n" + "\n".join(lines)

    def clear(self, include_pinned: bool = False) -> str:
        with self._lock:
            conn = self._connect()
            if include_pinned:
                conn.execute("DELETE FROM clipboard")
            else:
                conn.execute("DELETE FROM clipboard WHERE pinned = 0")
            conn.commit()
            conn.close()
        self._view_ids = []
        if include_pinned:
            return "Clipboard history cleared, including pinned items."
        return "Clipboard history cleared (pinned items kept)."

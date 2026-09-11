import os
import json
import time
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class SelfAwareness:
    """Self-awareness system: tracks own state, capabilities, history, and personality."""

    def __init__(self, db_path: str = "flexie_awareness.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._start_time = datetime.now()
        self._commands_processed = 0
        self._errors_encountered = 0
        self._features_used: Dict[str, int] = {}
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    command TEXT,
                    intent TEXT,
                    response TEXT,
                    success INTEGER,
                    duration_ms REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS personality (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT UNIQUE,
                    category TEXT,
                    confidence REAL DEFAULT 1.0,
                    learned_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def log_command(self, command: str, intent: str, response: str, success: bool, duration_ms: float):
        """Log a command execution for self-awareness."""
        self._commands_processed += 1
        self._features_used[intent] = self._features_used.get(intent, 0) + 1
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT INTO session_log (timestamp, command, intent, response, success, duration_ms) VALUES (?,?,?,?,?,?)",
                (time.time(), command, intent, response[:500], 1 if success else 0, duration_ms)
            )
            conn.commit()
            conn.close()

    def learn_fact(self, fact: str, category: str = "general", confidence: float = 1.0):
        """Learn a new fact about the user or world."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO user_facts (fact, category, confidence, learned_at) VALUES (?,?,?,?)",
                    (fact, category, confidence, time.time())
                )
                conn.commit()
            except Exception:
                pass
            conn.close()

    def recall_facts(self, category: Optional[str] = None, limit: int = 10) -> List[str]:
        """Recall learned facts."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            if category:
                rows = conn.execute(
                    "SELECT fact FROM user_facts WHERE category=? ORDER BY learned_at DESC LIMIT ?",
                    (category, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fact FROM user_facts ORDER BY learned_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()
        return [r[0] for r in rows]

    def get_self_info(self) -> str:
        """Return self-awareness information."""
        uptime = datetime.now() - self._start_time
        hours = int(uptime.total_seconds() // 3600)
        mins = int((uptime.total_seconds() % 3600) // 60)

        top_features = sorted(self._features_used.items(), key=lambda x: x[1], reverse=True)[:5]
        features_str = ", ".join(f"{k}({v})" for k, v in top_features) if top_features else "None yet"

        facts = self.recall_facts(limit=5)
        facts_str = "; ".join(facts) if facts else "No facts learned yet."

        return (
            f"I am Flexie, your AI desktop assistant. "
            f"Uptime: {hours}h {mins}m. "
            f"Commands processed: {self._commands_processed}. "
            f"Top features: {features_str}. "
            f"What I know: {facts_str}"
        )

    def get_stats(self) -> str:
        """Return detailed statistics."""
        uptime = datetime.now() - self._start_time
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            total = conn.execute("SELECT COUNT(*) FROM session_log").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM session_log WHERE success=1").fetchone()[0]
            avg_duration = conn.execute("SELECT AVG(duration_ms) FROM session_log").fetchone()[0] or 0
            facts_count = conn.execute("SELECT COUNT(*) FROM user_facts").fetchone()[0]
            conn.close()

        rate = (success / total * 100) if total > 0 else 0
        return (
            f"Stats: {total} total commands, {success} successful ({rate:.0f}% success rate). "
            f"Average response time: {avg_duration:.0f}ms. "
            f"Facts learned: {facts_count}. "
            f"Uptime: {int(uptime.total_seconds() // 3600)}h {int((uptime.total_seconds() % 3600) // 60)}m."
        )

    def get_personality(self) -> str:
        """Return personality traits."""
        return (
            "I am Flexie, a helpful and efficient AI assistant. "
            "I am concise, direct, and action-oriented. "
            "I learn from our conversations and remember important details about you. "
            "I am always improving and adapting to your preferences."
        )

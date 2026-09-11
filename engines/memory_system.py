import os
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


class MemorySystem:
    """Long-term memory system: remembers conversations, preferences, and context."""

    def __init__(self, db_path: str = "flexie_memory.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    user_message TEXT,
                    assistant_response TEXT,
                    intent TEXT,
                    topic TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    summary TEXT,
                    last_discussed REAL,
                    frequency INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reminder_text TEXT,
                    remind_at REAL,
                    created_at REAL,
                    completed INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()

    def remember_conversation(self, user_msg: str, assistant_msg: str, intent: str = "unknown"):
        """Store a conversation turn."""
        topic = self._extract_topic(user_msg)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT INTO conversations (timestamp, user_message, assistant_response, intent, topic) VALUES (?,?,?,?,?)",
                (time.time(), user_msg, assistant_msg[:1000], intent, topic)
            )
            # Update topic frequency
            existing = conn.execute("SELECT id, frequency FROM topics WHERE topic=?", (topic,)).fetchone()
            if existing:
                conn.execute("UPDATE topics SET frequency=?, last_discussed=? WHERE id=?",
                           (existing[1] + 1, time.time(), existing[0]))
            else:
                conn.execute("INSERT INTO topics (topic, summary, last_discussed) VALUES (?,?,?)",
                           (topic, user_msg[:200], time.time()))
            conn.commit()
            conn.close()

    def _extract_topic(self, message: str) -> str:
        """Extract main topic from a message."""
        words = message.lower().split()
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
                      "have", "has", "had", "do", "does", "did", "will", "would", "could",
                      "should", "may", "might", "can", "shall", "i", "you", "he", "she",
                      "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
                      "his", "its", "our", "their", "this", "that", "these", "those"}
        meaningful = [w for w in words if w not in stop_words and len(w) > 2]
        return " ".join(meaningful[:3]) if meaningful else "general"

    def set_preference(self, key: str, value: str):
        """Store a user preference."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?,?,?)",
                (key, value, time.time())
            )
            conn.commit()
            conn.close()

    def get_preference(self, key: str, default: str = "") -> str:
        """Get a user preference."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
            conn.close()
        return row[0] if row else default

    def get_recent_conversations(self, limit: int = 5) -> List[Dict]:
        """Get recent conversation history."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT user_message, assistant_response, intent, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
        return [{"user": r[0], "assistant": r[1], "intent": r[2], "time": r[3]} for r in rows]

    def get_popular_topics(self, limit: int = 5) -> List[Dict]:
        """Get most discussed topics."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT topic, frequency, last_discussed FROM topics ORDER BY frequency DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
        return [{"topic": r[0], "frequency": r[1], "last_discussed": r[2]} for r in rows]

    def get_context_summary(self) -> str:
        """Get a summary of what we've discussed recently."""
        recent = self.get_recent_conversations(3)
        if not recent:
            return "No recent conversations."
        topics = self.get_popular_topics(3)
        topics_str = ", ".join(t["topic"] for t in topics) if topics else "various topics"
        return f"Recent topics: {topics_str}. Last thing we discussed: {recent[0]['user'][:50]}..."

    def search_memory(self, query: str) -> List[str]:
        """Search memory for relevant information."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT user_message, assistant_response FROM conversations WHERE user_message LIKE ? OR assistant_response LIKE ? ORDER BY timestamp DESC LIMIT 5",
                (f"%{query}%", f"%{query}%")
            ).fetchall()
            conn.close()
        results = []
        for user, assistant in rows:
            results.append(f"Q: {user[:80]}... A: {assistant[:80]}...")
        return results if results else [f"No memory found about '{query}'."]

    def get_memory_stats(self) -> str:
        """Get memory statistics."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            pref_count = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
            topic_count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            conn.close()
        return f"Memory: {conv_count} conversations, {pref_count} preferences, {topic_count} topics tracked."

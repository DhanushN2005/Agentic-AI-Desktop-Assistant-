import threading
import time

from core.memory_manager import scrub
from utils.paths import data_file
from utils.sql_like import like_contains
from utils.sqlite_util import fast_connect


class MemorySystem:
    """Long-term memory system: remembers conversations, preferences, and context."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or data_file("flexie_memory.db")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = fast_connect(self._db_path)
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
            # Dedupe legacy duplicate topics (merge frequencies), then enforce uniqueness.
            conn.execute("""
                UPDATE topics SET frequency = (
                    SELECT SUM(t2.frequency) FROM topics t2 WHERE t2.topic = topics.topic)
                WHERE id IN (SELECT MAX(id) FROM topics GROUP BY topic HAVING COUNT(*) > 1)
            """)
            conn.execute("""
                DELETE FROM topics WHERE id NOT IN (SELECT MAX(id) FROM topics GROUP BY topic)
            """)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_topics_topic ON topics(topic)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_ts ON conversations(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_topics_last ON topics(last_discussed)")
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
        """Store a conversation turn (secrets masked; one atomic transaction)."""
        user_msg, assistant_msg = scrub(user_msg), scrub(assistant_msg)
        topic = self._extract_topic(user_msg)
        now = time.time()
        with self._lock:
            with fast_connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO conversations (timestamp, user_message, assistant_response, intent, topic) VALUES (?,?,?,?,?)",
                    (now, user_msg, assistant_msg[:1000], intent, topic)
                )
                conn.execute(
                    "INSERT INTO topics (topic, summary, last_discussed) VALUES (?,?,?) "
                    "ON CONFLICT(topic) DO UPDATE SET frequency = frequency + 1, last_discussed = excluded.last_discussed",
                    (topic, user_msg[:200], now))

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
        """Store a user preference (secrets masked)."""
        key, value = scrub(key), scrub(value)
        with self._lock:
            conn = fast_connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?,?,?)",
                (key, value, time.time())
            )
            conn.commit()
            conn.close()

    def forget_everywhere(self, text: str) -> dict[str, int]:
        """Delete ``text`` from preferences, conversations and topics. Returns counts per table."""
        pat = like_contains(text)
        with self._lock:
            with fast_connect(self._db_path) as conn:
                counts = {
                    "preferences": conn.execute(
                        "DELETE FROM preferences WHERE key LIKE ? ESCAPE '!' OR value LIKE ? ESCAPE '!'",
                        (pat, pat)).rowcount,
                    "conversations": conn.execute(
                        "DELETE FROM conversations WHERE user_message LIKE ? ESCAPE '!' "
                        "OR assistant_response LIKE ? ESCAPE '!'", (pat, pat)).rowcount,
                    "topics": conn.execute(
                        "DELETE FROM topics WHERE topic LIKE ? ESCAPE '!' OR summary LIKE ? ESCAPE '!'",
                        (pat, pat)).rowcount,
                }
        return {k: v for k, v in counts.items() if v and v > 0}

    def forget_matching(self, text: str) -> int:
        """Delete preferences, conversations and topics containing ``text``. Returns rows removed."""
        return sum(self.forget_everywhere(text).values())

    def prune(self, max_conversations: int = 5000, max_topics: int = 2000) -> dict[str, int]:
        """Delete the oldest conversations / least recently discussed topics beyond the caps."""
        with self._lock:
            with fast_connect(self._db_path) as conn:
                out = {
                    "conversations": conn.execute(
                        "DELETE FROM conversations WHERE id <= "
                        "(SELECT id FROM conversations ORDER BY id DESC LIMIT 1 OFFSET ?)",
                        (max(0, max_conversations),)).rowcount,
                    "topics": conn.execute(
                        "DELETE FROM topics WHERE id IN (SELECT id FROM topics "
                        "ORDER BY last_discussed DESC, id DESC LIMIT -1 OFFSET ?)",
                        (max(0, max_topics),)).rowcount,
                }
        return {k: v for k, v in out.items() if v and v > 0}

    def get_preference(self, key: str, default: str = "") -> str:
        """Get a user preference."""
        with self._lock:
            conn = fast_connect(self._db_path)
            row = conn.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
            conn.close()
        return row[0] if row else default

    def get_recent_conversations(self, limit: int = 5) -> list[dict]:
        """Get recent conversation history."""
        with self._lock:
            conn = fast_connect(self._db_path)
            rows = conn.execute(
                "SELECT user_message, assistant_response, intent, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
        return [{"user": r[0], "assistant": r[1], "intent": r[2], "time": r[3]} for r in rows]

    def get_popular_topics(self, limit: int = 5) -> list[dict]:
        """Get most discussed topics."""
        with self._lock:
            conn = fast_connect(self._db_path)
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

    def search_memory(self, query: str) -> list[str]:
        """Search memory for relevant information."""
        with self._lock:
            conn = fast_connect(self._db_path)
            rows = conn.execute(
                "SELECT user_message, assistant_response FROM conversations "
                "WHERE user_message LIKE ? ESCAPE '!' OR assistant_response LIKE ? ESCAPE '!' "
                "ORDER BY timestamp DESC LIMIT 5",
                (like_contains(query), like_contains(query))
            ).fetchall()
            conn.close()
        results = []
        for user, assistant in rows:
            results.append(f"Q: {user[:80]}... A: {assistant[:80]}...")
        return results  # empty list when nothing matches; callers phrase the "not found" reply

    def get_memory_stats(self) -> str:
        """Get memory statistics."""
        with self._lock:
            conn = fast_connect(self._db_path)
            conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            pref_count = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
            topic_count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            conn.close()
        return f"Memory: {conv_count} conversations, {pref_count} preferences, {topic_count} topics tracked."

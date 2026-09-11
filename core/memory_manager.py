"""
Memory Manager — structured memory with clear categories.

Separates memory into:
  SHORT_TERM_CONTEXT — current session state
  CONVERSATION_HISTORY — past conversation turns
  USER_PREFERENCES — persistent user settings
  LONG_TERM_FACTS — important facts learned
  TASK_HISTORY — past task executions
  WORKSPACE_MEMORY — project/file context

Each entry has:
  timestamp, source, confidence, category, importance, expiration

Provides commands:
  "What do you remember about me?"
  "Forget that."
  "Forget everything about X."
  "Why do you remember this?"
"""
import time
import json
import logging
import os
import sqlite3
from enum import Enum, auto
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


class MemoryCategory(Enum):
    SHORT_TERM = auto()       # Current session only
    CONVERSATION = auto()     # Past conversation turns
    PREFERENCES = auto()      # User preferences
    FACTS = auto()            # Important facts
    TASKS = auto()            # Task execution history
    WORKSPACE = auto()        # Project/file context


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""
    key: str
    value: Any
    category: MemoryCategory
    timestamp: float = field(default_factory=time.time)
    source: str = "user"  # "user", "system", "inferred"
    confidence: float = 1.0  # 0.0 to 1.0
    importance: float = 0.5  # 0.0 to 1.0
    expiration: Optional[float] = None  # Unix timestamp, None = never
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expiration is None:
            return False
        return time.time() > self.expiration

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category.name,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "importance": self.importance,
            "expiration": self.expiration,
            "tags": self.tags,
        }


class MemoryManager:
    """
    Centralized memory management with structured categories.
    
    Wraps the existing MemoryEngine with additional categorization
    and metadata support.
    """

    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "memory_structured.db")

    def __init__(self):
        self.logger = logging.getLogger("Flexie.MemoryManager")
        self._entries: Dict[str, MemoryEntry] = {}
        self._ensure_db()
        self._load()

    def _ensure_db(self):
        """Create database tables if they don't exist."""
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
        conn = sqlite3.connect(self.DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                key TEXT PRIMARY KEY,
                value TEXT,
                category TEXT,
                timestamp REAL,
                source TEXT,
                confidence REAL,
                importance REAL,
                expiration REAL,
                tags TEXT,
                metadata TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _load(self):
        """Load memories from database."""
        try:
            conn = sqlite3.connect(self.DB_PATH)
            c = conn.cursor()
            c.execute("SELECT * FROM memories")
            for row in c.fetchall():
                key, value, cat_name, ts, src, conf, imp, exp, tags_json, meta_json = row
                try:
                    category = MemoryCategory[cat_name]
                except KeyError:
                    category = MemoryCategory.FACTS
                entry = MemoryEntry(
                    key=key,
                    value=json.loads(value) if value else "",
                    category=category,
                    timestamp=ts,
                    source=src,
                    confidence=conf,
                    importance=imp,
                    expiration=exp,
                    tags=json.loads(tags_json) if tags_json else [],
                    metadata=json.loads(meta_json) if meta_json else {},
                )
                self._entries[key] = entry
            conn.close()
            self.logger.info(f"[MEMORY] Loaded {len(self._entries)} entries from DB")
        except Exception as e:
            self.logger.warning(f"[MEMORY] Failed to load from DB: {e}")

    def _save(self):
        """Persist memories to database."""
        try:
            conn = sqlite3.connect(self.DB_PATH)
            c = conn.cursor()
            for entry in self._entries.values():
                c.execute("""
                    INSERT OR REPLACE INTO memories
                    (key, value, category, timestamp, source, confidence, importance, expiration, tags, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry.key,
                    json.dumps(entry.value) if not isinstance(entry.value, str) else entry.value,
                    entry.category.name,
                    entry.timestamp,
                    entry.source,
                    entry.confidence,
                    entry.importance,
                    entry.expiration,
                    json.dumps(entry.tags),
                    json.dumps(entry.metadata),
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"[MEMORY] Failed to save to DB: {e}")

    def remember(
        self,
        key: str,
        value: Any,
        category: MemoryCategory = MemoryCategory.FACTS,
        source: str = "user",
        confidence: float = 1.0,
        importance: float = 0.5,
        expiration: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Store a memory entry."""
        entry = MemoryEntry(
            key=key.lower().strip(),
            value=value,
            category=category,
            source=source,
            confidence=confidence,
            importance=importance,
            expiration=expiration,
            tags=tags or [],
        )
        self._entries[entry.key] = entry
        self._save()
        self.logger.info(f"[MEMORY] Stored: {entry.key} ({category.name})")
        return True

    def recall(self, key: str) -> Optional[MemoryEntry]:
        """Recall a specific memory by key."""
        entry = self._entries.get(key.lower().strip())
        if entry and not entry.is_expired:
            return entry
        return None

    def search(self, query: str, category: Optional[MemoryCategory] = None, limit: int = 10) -> List[MemoryEntry]:
        """Search memories by query string."""
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            if entry.is_expired:
                continue
            if category and entry.category != category:
                continue
            if query_lower in entry.key or query_lower in str(entry.value).lower():
                results.append(entry)
            elif any(query_lower in tag for tag in entry.tags):
                results.append(entry)
        # Sort by importance * confidence
        results.sort(key=lambda e: e.importance * e.confidence, reverse=True)
        return results[:limit]

    def forget(self, key: str) -> bool:
        """Remove a specific memory."""
        key = key.lower().strip()
        if key in self._entries:
            del self._entries[key]
            self._save()
            self.logger.info(f"[MEMORY] Forgot: {key}")
            return True
        return False

    def forget_category(self, category: MemoryCategory) -> int:
        """Remove all memories in a category."""
        keys = [k for k, v in self._entries.items() if v.category == category]
        for k in keys:
            del self._entries[k]
        self._save()
        self.logger.info(f"[MEMORY] Forgot {len(keys)} entries in {category.name}")
        return len(keys)

    def get_by_category(self, category: MemoryCategory) -> List[MemoryEntry]:
        """Get all memories in a category."""
        return [e for e in self._entries.values() if e.category == category and not e.is_expired]

    def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """Get most recent memories."""
        entries = [e for e in self._entries.values() if not e.is_expired]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def get_important(self, min_importance: float = 0.7, limit: int = 10) -> List[MemoryEntry]:
        """Get high-importance memories."""
        entries = [e for e in self._entries.values()
                   if not e.is_expired and e.importance >= min_importance]
        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        active = [e for e in self._entries.values() if not e.is_expired]
        expired = [e for e in self._entries.values() if e.is_expired]
        by_category = {}
        for cat in MemoryCategory:
            by_category[cat.name] = len([e for e in active if e.category == cat])
        return {
            "total": len(self._entries),
            "active": len(active),
            "expired": len(expired),
            "by_category": by_category,
        }

    def cleanup_expired(self) -> int:
        """Remove expired entries."""
        keys = [k for k, v in self._entries.items() if v.is_expired]
        for k in keys:
            del self._entries[k]
        if keys:
            self._save()
        return len(keys)

    def to_summary(self) -> str:
        """Human-readable memory summary."""
        stats = self.get_stats()
        lines = [
            f"Memory: {stats['active']}/{stats['total']} active",
            "By category:",
        ]
        for cat, count in stats["by_category"].items():
            if count > 0:
                lines.append(f"  {cat}: {count}")
        return "\n".join(lines)

    def explain(self, key: str) -> str:
        """Explain why a memory is stored."""
        entry = self.recall(key)
        if not entry:
            return f"No memory found for '{key}'"
        return (
            f"Memory '{entry.key}':\n"
            f"  Value: {entry.value}\n"
            f"  Category: {entry.category.name}\n"
            f"  Source: {entry.source}\n"
            f"  Confidence: {entry.confidence:.1%}\n"
            f"  Importance: {entry.importance:.1%}\n"
            f"  Stored: {time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.timestamp))}\n"
            f"  Tags: {', '.join(entry.tags) if entry.tags else 'none'}"
        )

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
import hashlib
import heapq
import json
import logging
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache
from itertools import chain
from typing import Any

from utils.sqlite_util import fast_connect


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
    expiration: float | None = None  # Unix timestamp, None = never
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

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


# ---------------------------------------------------------------------------
# Redaction (MM-9): one helper applied before every store path.
# ---------------------------------------------------------------------------
REDACTED = "[REDACTED]"

_KEY_SHAPES = re.compile(
    r"\b(?:sk-ant-|sk-|gsk_|gh[pousr]_|github_pat_|xox[abprs]-|glpat-|hf_|AIza|AKIA|ASIA|"
    r"SG\.|rk_live_|sk_live_)[A-Za-z0-9_\-.]{12,}"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}")
_LABELLED = re.compile(
    r"(?i)\b(pass(?:word|code|phrase|wd)?|pwd|secret|api[ _-]?key|access[ _-]?key|credentials?)"
    r"\b(\s*(?:is|was|are|=|:)\s*)(?!\[REDACTED\])([^\s,;]+)"
)
_TOKEN_LABELLED = re.compile(r"(?i)\b((?:access|auth|api|refresh|bearer)?[ _-]?token)\b(\s*[:=]\s*)(?!\[REDACTED\])([^\s,;]+)")
_NUMERIC_CODE = re.compile(
    r"(?i)\b(otp|pin|cvv|cvc|passcode|verification code|security code|one[- ]time (?:password|code))\b"
    r"(\s*(?:is|was|:|=|code)?\s*)(\d{3,8})\b"
)
_HEX_SECRET = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_B64_SECRET = re.compile(r"(?<![A-Za-z0-9+/_=\-])[A-Za-z0-9+/_=\-]{40,}(?![A-Za-z0-9+/_=\-])")


def _b64_sub(m: "re.Match") -> str:
    """Mask only random-looking runs: mixed case AND digits (file names/words are not)."""
    t = m.group(0)
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return t
    upper = sum(c.isupper() for c in letters) / len(letters)
    digits = sum(c.isdigit() for c in t)
    if 0.2 <= upper <= 0.8 and digits >= 2:
        return REDACTED
    return t


_QUICK = re.compile(
    r"(?i)sk-|gsk_|gh[pousr]_|github_pat_|xox|glpat-|hf_|AIza|AKIA|ASIA|SG\.|_live_|bearer|pass|pwd|secret|key|"
    r"credential|token|otp|pin|cvv|cvc|code|one[- ]time|[A-Za-z0-9+/_=\-]{32,}"
)


def scrub(text):
    """Mask passwords, PINs, OTPs, API keys, tokens and long secret-looking strings.

    Non-string input is returned unchanged. Safe to call on every write (~10 us for a
    typical utterance).
    """
    if not isinstance(text, str) or len(text) < 4 or _QUICK.search(text) is None:
        return text  # cheap pre-filter: nothing that could be a secret
    out = _KEY_SHAPES.sub(REDACTED, text)
    out = _BEARER.sub("Bearer " + REDACTED, out)
    out = _LABELLED.sub(lambda m: m.group(1) + m.group(2) + REDACTED, out)
    out = _TOKEN_LABELLED.sub(lambda m: m.group(1) + m.group(2) + REDACTED, out)
    out = _NUMERIC_CODE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, out)
    out = _HEX_SECRET.sub(REDACTED, out)
    if len(out) >= 40:
        out = _B64_SECRET.sub(_b64_sub, out)
    return out


def contains_secret(text) -> bool:
    """True when ``scrub`` would change ``text`` (it must then never reach the vector store)."""
    return isinstance(text, str) and scrub(text) != text


# ---------------------------------------------------------------------------
# Tokenisation for recall (MM-2)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = frozenset(
    "a an the is are was were be been being am do does did done have has had will would could should may might can "
    "shall i you he she it we they me him her us them my your his its our their this that these those what which "
    "who whom whose when where why how and or but if then so of to in on at by for with from as into about "
    "please tell show give get let know remember recall any some there here also just not no yes ok okay hey "
    "flexie s t".split()
)


@lru_cache(maxsize=65536)
def _stem(w: str) -> str:
    n = len(w)
    if n > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if n > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    n = len(w)
    if n > 5 and w.endswith("ing"):
        w = w[:-3]
    elif n > 4 and w.endswith("ed"):
        w = w[:-2]
    return w


def _tokenize(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if raw in _STOP_WORDS or (len(raw) < 2 and not raw.isdigit()):
            continue
        seen[_stem(raw)] = None
    return list(seen)


class MemoryManager:
    """
    Centralized memory management with structured categories.

    Wraps the existing MemoryEngine with additional categorization
    and metadata support. Thread-safe: every access to ``_entries`` is guarded by an
    RLock and readers iterate over snapshots.
    """

    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "memory_structured.db")
    WIKI_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
    WS_DIR = os.path.join(os.path.dirname(__file__), "..", "workspace")

    # Retention (MM-8): default time-to-live per category, via the ``expiration`` field.
    _DEFAULT_TTL = {
        MemoryCategory.CONVERSATION: 14 * 86400.0,
        MemoryCategory.TASKS: 30 * 86400.0,
    }
    _MAX_CONVERSATION_ENTRIES = 5000
    # Wiki only follows these categories; each section is capped to the top-N by importance.
    _WIKI_CATEGORIES = frozenset({MemoryCategory.FACTS, MemoryCategory.PREFERENCES, MemoryCategory.WORKSPACE})
    _WIKI_TOP_N = {MemoryCategory.PREFERENCES: 100, MemoryCategory.FACTS: 100, MemoryCategory.WORKSPACE: 100,
                   MemoryCategory.TASKS: 10, MemoryCategory.CONVERSATION: 10}

    # Class-level defaults so instances built without __init__ (tests) still work.
    _lock = threading.RLock()
    _tok: dict | None = None
    _post: dict | None = None
    _load_failed = False
    _load_skipped = 0
    _wiki_ok = True
    _wiki_retries = 0

    def __init__(self):
        self.logger = logging.getLogger("Flexie.MemoryManager")
        self._lock = threading.RLock()
        self._entries: dict[str, MemoryEntry] = {}
        self._ensure_db()
        self._load()

    # ------------------------------------------------------------------ DB --
    def _ensure_db(self):
        """Create database tables if they don't exist."""
        os.makedirs(os.path.dirname(os.path.abspath(self.DB_PATH)), exist_ok=True)
        conn = fast_connect(self.DB_PATH)
        try:
            # WAL mode: readers don't block writers (single-writer still serialised).
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception as _e:
                logging.debug("[core/memory_manager.py:WAL] Swallowed exception: %s: %s", type(_e).__name__, _e)
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
            cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
            if "vfmt" not in cols:
                # vfmt=1: value column is always JSON-encoded. 0 = legacy (strings were stored raw).
                conn.execute("ALTER TABLE memories ADD COLUMN vfmt INTEGER DEFAULT 0")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _decode_value(raw, vfmt: int):
        """Decode a stored value; never raises. Legacy rows keep ambiguous scalars as strings."""
        if raw is None or raw == "":
            return ""
        try:
            val = json.loads(raw)
        except (TypeError, ValueError):
            return raw  # legacy raw string
        if vfmt:
            return val
        # Legacy rows: strings were saved raw, structures via json.dumps. A bare scalar
        # ("123", "true", "null") was far more likely a string than a number.
        return val if isinstance(val, (dict, list, str)) else raw

    def _load(self):
        """Load memories from database. One bad row never aborts the load (MM-1)."""
        self._load_failed = False
        self._load_skipped = 0
        try:
            conn = fast_connect(self.DB_PATH)
            now = time.time()
            # Backfill retention on legacy rows so old conversation rows age out.
            for cat, ttl in self._DEFAULT_TTL.items():
                conn.execute(
                    "UPDATE memories SET expiration = timestamp + ? WHERE category = ? AND expiration IS NULL",
                    (ttl, cat.name),
                )
            rows = conn.execute(
                "SELECT key, value, category, timestamp, source, confidence, importance, expiration, "
                "tags, metadata, vfmt FROM memories"
            ).fetchall()
        except Exception as e:
            self._load_failed = True
            self.logger.warning(f"[MEMORY] Failed to load from DB: {e}")
            return
        loaded: dict[str, MemoryEntry] = {}
        migrate: list[tuple] = []
        expired: list[tuple] = []
        for row in rows:
            try:
                key, value, cat_name, ts, src, conf, imp, exp, tags_json, meta_json, vfmt = row
                if exp is not None and now > exp:
                    expired.append((key,))
                    continue
                try:
                    category = MemoryCategory[cat_name]
                except KeyError:
                    category = MemoryCategory.FACTS
                val = self._decode_value(value, vfmt or 0)
                try:
                    tags = json.loads(tags_json) if tags_json else []
                    tags = [str(t) for t in tags] if isinstance(tags, list) else []
                except (TypeError, ValueError):
                    tags = []
                try:
                    meta = json.loads(meta_json) if meta_json else {}
                    meta = meta if isinstance(meta, dict) else {}
                except (TypeError, ValueError):
                    meta = {}
                loaded[key] = MemoryEntry(
                    key=key, value=val, category=category,
                    timestamp=ts if ts is not None else now,
                    source=src or "user",
                    confidence=conf if conf is not None else 1.0,
                    importance=imp if imp is not None else 0.5,
                    expiration=exp, tags=tags, metadata=meta,
                )
                if not vfmt:
                    migrate.append((json.dumps(val, ensure_ascii=False, default=str), key))
            except Exception as e:  # noqa: BLE001
                self._load_skipped += 1
                self.logger.warning(f"[MEMORY] Skipping unreadable memory row: {e}")
        with self._lock:
            self._entries.update(loaded)
            self._tok = self._post = self._meta = None
            self._ensure_index()  # pay the tokenising cost at startup, not on the first ask
        try:
            with fast_connect(self.DB_PATH) as c2:
                if migrate:
                    c2.executemany("UPDATE memories SET value = ?, vfmt = 1 WHERE key = ?", migrate)
                if expired:
                    c2.executemany("DELETE FROM memories WHERE key = ?", expired)
        except Exception as e:  # noqa: BLE001
            self.logger.warning(f"[MEMORY] Memory migration/cleanup failed: {e}")
        self.logger.info(f"[MEMORY] Loaded {len(self._entries)} entries from DB")

    @staticmethod
    def _row_for(entry: "MemoryEntry") -> tuple:
        return (
            entry.key,
            json.dumps(entry.value, ensure_ascii=False, default=str),
            entry.category.name,
            entry.timestamp,
            entry.source,
            entry.confidence,
            entry.importance,
            entry.expiration,
            json.dumps(entry.tags),
            json.dumps(entry.metadata, default=str),
            1,
        )

    _INSERT_SQL = """
        INSERT OR REPLACE INTO memories
        (key, value, category, timestamp, source, confidence, importance, expiration, tags, metadata, vfmt)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    _db_cache: tuple | None = None

    def _db(self):
        """Cached connection proxy for DB_PATH (re-resolved if DB_PATH changes)."""
        cached = self._db_cache
        if cached is None or cached[0] != self.DB_PATH:
            cached = self._db_cache = (self.DB_PATH, fast_connect(self.DB_PATH))
        return cached[1]

    def _save_entry(self, entry: "MemoryEntry"):
        """Persist a single entry (INSERT OR REPLACE) — O(1), no full rewrite."""
        try:
            with self._db() as conn:
                conn.execute(self._INSERT_SQL, self._row_for(entry))
        except Exception as e:
            self.logger.warning(f"[MEMORY] Failed to save entry {entry.key}: {e}")

    def _delete_key(self, key: str):
        """Delete a single row — O(1), no full rewrite."""
        self._delete_keys([key])

    def _delete_keys(self, keys: list[str]):
        if not keys:
            return
        try:
            with self._db() as conn:
                conn.executemany("DELETE FROM memories WHERE key = ?", [(k,) for k in keys])
        except Exception as e:
            self.logger.warning(f"[MEMORY] Failed to delete {len(keys)} entries: {e}")

    def _save(self):
        """Persist memories to database (full sync; prefer _save_entry for single rows)."""
        try:
            with self._lock:
                rows = [self._row_for(entry) for entry in list(self._entries.values())]
            with fast_connect(self.DB_PATH) as conn:
                conn.executemany(self._INSERT_SQL, rows)
        except Exception as e:
            self.logger.warning(f"[MEMORY] Failed to save to DB: {e}")

    # --------------------------------------------------------------- index --
    _meta: dict | None = None

    @staticmethod
    def _entry_tokens(e: "MemoryEntry") -> tuple[frozenset, frozenset]:
        key_t = frozenset(_tokenize(e.key))
        body = e.value if isinstance(e.value, str) else json.dumps(e.value, default=str)
        all_t = set(key_t)
        all_t.update(_tokenize(body[:2000]))
        for t in e.tags:
            all_t.update(_tokenize(str(t)))
        return frozenset(all_t), key_t

    @staticmethod
    def _static_weight(e: "MemoryEntry", now: float) -> float:
        """importance x confidence x recency decay (half-life 90 days, floor 0.3)."""
        decay = max(0.3, 0.5 ** (max(0.0, now - e.timestamp) / (90 * 86400.0)))
        return max(e.importance, 0.05) * max(e.confidence, 0.05) * decay

    def _index_remove(self, key: str) -> None:
        if self._tok is None:
            return
        old = self._tok.pop(key, None)
        self._meta.pop(key, None)
        if old:
            for t in old[0]:
                keys = self._post.get(t)
                if keys is not None:
                    keys.discard(key)
                    if not keys:
                        del self._post[t]

    def _index_add(self, entry: "MemoryEntry", now: float | None = None) -> None:
        if self._tok is None:
            return
        self._index_remove(entry.key)
        toks = self._entry_tokens(entry)
        self._tok[entry.key] = toks
        self._meta[entry.key] = (self._static_weight(entry, now or time.time()), entry.expiration, entry.category)
        for t in toks[0]:
            self._post.setdefault(t, set()).add(entry.key)

    def _ensure_index(self) -> None:
        if self._tok is not None and len(self._tok) == len(self._entries):
            return
        self._tok, self._post, self._meta = {}, {}, {}
        now = time.time()
        for e in list(self._entries.values()):
            self._index_add(e, now)

    # ----------------------------------------------------------------- API --
    def _wiki_relevant(self, *cats: MemoryCategory) -> bool:
        return any(c in self._WIKI_CATEGORIES for c in cats)

    def remember(
        self,
        key: str,
        value: Any,
        category: MemoryCategory = MemoryCategory.FACTS,
        source: str = "user",
        confidence: float = 1.0,
        importance: float = 0.5,
        expiration: float | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """Store a memory entry (secrets are masked before storage)."""
        clean_key = scrub(key)
        clean_val = scrub(value)
        key = clean_key.lower().strip()
        if (category == MemoryCategory.CONVERSATION and isinstance(clean_val, str)
                and len(key) >= 20 and len(clean_val.strip()) > len(key)
                and clean_val.lower().strip().startswith(key)):
            # Key is a truncated prefix of the text: different texts sharing a prefix must not collide.
            key = f"{key}#{hashlib.sha1(clean_val.encode('utf-8', 'replace')).hexdigest()[:8]}"
        if expiration is None:
            ttl = self._DEFAULT_TTL.get(category)
            if ttl:
                expiration = time.time() + ttl
        entry = MemoryEntry(
            key=key,
            value=clean_val,
            category=category,
            source=source,
            confidence=confidence,
            importance=importance,
            expiration=expiration,
            tags=tags or [],
        )
        if clean_val != value and isinstance(value, str):
            entry.metadata["redacted"] = True
        with self._lock:
            self._entries[entry.key] = entry
            self._index_add(entry)
            self._save_entry(entry)
        self.logger.info(f"[MEMORY] Stored: {entry.key} ({category.name})")
        if self._wiki_relevant(category):
            self.sync_markdown_wiki()
        return True

    def recall(self, key: str) -> MemoryEntry | None:
        """Recall a specific memory by key."""
        entry = self._entries.get(key.lower().strip())
        if entry and not entry.is_expired:
            return entry
        return None

    def search(
        self,
        query: str,
        category: MemoryCategory | None = None,
        limit: int = 10,
        exclude_categories=None,
    ) -> list[MemoryEntry]:
        """Token-overlap search weighted by importance x confidence x recency decay.

        ``exclude_categories`` lets RAG callers drop e.g. ``MemoryCategory.CONVERSATION``.
        """
        excluded = frozenset(exclude_categories or ())
        qtok = _tokenize(query)
        query_lower = (query or "").lower().strip()
        now = time.time()
        top: list[MemoryEntry] = []
        limit = max(0, limit)

        with self._lock:
            ranked: list[tuple[float, str]] = []
            if qtok:
                self._ensure_index()
                post, meta, tok = self._post, self._meta, self._tok
                counts = Counter(chain.from_iterable(post[t] for t in qtok if t in post))
                nq = len(qtok)
                for k, n in counts.items():
                    cov = n / nq
                    if n < 2 and cov < 0.2:
                        continue  # one stray word of a long prompt is noise
                    w, exp, cat = meta[k]
                    if (exp is not None and now > exp) or cat in excluded or (category and cat != category):
                        continue
                    ranked.append((cov * w, k))
                best = heapq.nlargest(limit * 3 + 3, ranked)
                # key-match bonus is applied to the short list only (cheap)
                rescored = []
                for sc, k in best:
                    bonus = 0.25 if any(t in tok[k][1] for t in qtok) else 0.0
                    rescored.append((sc + bonus * meta[k][0], k))
                rescored.sort(reverse=True)
                top = [self._entries[k] for _, k in rescored[:limit] if k in self._entries]
            if not top and query_lower and len(query_lower) <= 120:
                # Fallback: literal substring (partial words, punctuation-only queries).
                hits: list[tuple[float, float, MemoryEntry]] = []
                for e in list(self._entries.values()):
                    if e.category in excluded or (category and e.category != category):
                        continue
                    if e.expiration is not None and now > e.expiration:
                        continue
                    if (query_lower in e.key or query_lower in str(e.value).lower()
                            or any(query_lower in tag for tag in e.tags)):
                        hits.append((self._static_weight(e, now), e.timestamp, e))
                hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
                top = [e for _, _, e in hits[:limit]]
        return top

    def forget(self, key: str) -> bool:
        """Remove a specific memory."""
        key = key.lower().strip()
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry is None:
                return False
            self._index_remove(key)
            self._delete_key(key)
        self.logger.info(f"[MEMORY] Forgot: {key}")
        if self._wiki_relevant(entry.category):
            self.sync_markdown_wiki()
        return True

    def _remove_entries(self, keys: list[str]) -> list["MemoryEntry"]:
        removed = []
        with self._lock:
            for k in keys:
                e = self._entries.pop(k, None)
                if e is not None:
                    removed.append(e)
                    self._index_remove(k)
            self._delete_keys(keys)
        return removed

    def forget_matching(self, text: str) -> int:
        """Remove every memory whose key, value or tags contain ``text`` (case-insensitive)."""
        needle = text.lower().strip()
        if not needle:
            return 0
        with self._lock:
            keys = [k for k, e in list(self._entries.items())
                    if needle in k or needle in str(e.value).lower() or any(needle in t for t in e.tags)]
            removed = self._remove_entries(keys)
        if removed:
            self.logger.info(f"[MEMORY] Forgot {len(removed)} entries matching {needle!r}")
            if self._wiki_relevant(*{e.category for e in removed}):
                self.sync_markdown_wiki()
        return len(removed)

    def forget_category(self, category: MemoryCategory) -> int:
        """Remove all memories in a category."""
        with self._lock:
            keys = [k for k, v in list(self._entries.items()) if v.category == category]
            self._remove_entries(keys)
        self.logger.info(f"[MEMORY] Forgot {len(keys)} entries in {category.name}")
        if keys and self._wiki_relevant(category):
            self.sync_markdown_wiki()
        return len(keys)

    def get_by_category(self, category: MemoryCategory) -> list[MemoryEntry]:
        """Get all memories in a category."""
        with self._lock:
            return [e for e in list(self._entries.values()) if e.category == category and not e.is_expired]

    def get_recent(self, limit: int = 10) -> list[MemoryEntry]:
        """Get most recent memories."""
        with self._lock:
            entries = [e for e in list(self._entries.values()) if not e.is_expired]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def get_important(self, min_importance: float = 0.7, limit: int = 10) -> list[MemoryEntry]:
        """Get high-importance memories."""
        with self._lock:
            entries = [e for e in list(self._entries.values())
                       if not e.is_expired and e.importance >= min_importance]
        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        with self._lock:
            snapshot = list(self._entries.values())
        active = [e for e in snapshot if not e.is_expired]
        expired = [e for e in snapshot if e.is_expired]
        by_category = {}
        for cat in MemoryCategory:
            by_category[cat.name] = len([e for e in active if e.category == cat])
        return {
            "total": len(snapshot),
            "active": len(active),
            "expired": len(expired),
            "by_category": by_category,
        }

    def cleanup_expired(self) -> int:
        """Remove expired entries and cap CONVERSATION entries (oldest go first)."""
        with self._lock:
            snapshot = list(self._entries.items())
            keys = [k for k, v in snapshot if v.is_expired]
            conv = sorted(((v.timestamp, k) for k, v in snapshot
                           if v.category == MemoryCategory.CONVERSATION and not v.is_expired))
            overflow = len(conv) - self._MAX_CONVERSATION_ENTRIES
            if overflow > 0:
                keys.extend(k for _, k in conv[:overflow])
            removed = self._remove_entries(keys)
        if removed and self._wiki_relevant(*{e.category for e in removed}):
            self.sync_markdown_wiki()
        return len(removed)

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

    @staticmethod
    def _write_atomic(path: str, content: str) -> bool:
        """Write ``content`` to ``path`` via a temp file + os.replace (never a torn file)."""
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            for attempt in range(3):
                try:
                    os.replace(tmp, path)
                    return True
                except PermissionError:  # reader (editor/AV) holds the file on Windows
                    if attempt == 2:
                        raise
                    time.sleep(0.03)
            return False
        except Exception as err:  # noqa: BLE001
            logging.getLogger("Flexie.MemoryManager").warning(f"[MEMORY] Could not write wiki {path}: {err}")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def export_to_markdown(self, filepath: str | None = None) -> str:
        """Export structured memories to a human-readable Markdown wiki (atomic writes).

        Only the top-N entries per section (by importance) are written. Nothing is written
        when the DB load failed, so an unreadable database can never replace a good wiki
        with an empty one.
        """
        if filepath is None:
            filepath = os.path.join(self.WIKI_DIR, "MEMORY.md")

        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "# 🧠 Flexiee Personal Knowledge Wiki",
            f"*Last synchronized: {now_str}*",
            "",
            "> Human-readable, Flexie memory wiki persistent across restarts.",
            "",
        ]

        with self._lock:
            active_entries = [e for e in list(self._entries.values()) if not e.is_expired]

        sections = [
            (MemoryCategory.PREFERENCES, "🌟 User Preferences & Personalization"),
            (MemoryCategory.FACTS, "📌 Learned Facts & Knowledge"),
            (MemoryCategory.WORKSPACE, "💻 Workspace & Project Context"),
            (MemoryCategory.TASKS, "⚡ Task Execution Records"),
            (MemoryCategory.CONVERSATION, "💬 Conversation Notes"),
        ]

        for cat, title in sections:
            cat_entries = [e for e in active_entries if e.category == cat]
            if cat_entries:
                lines.append(f"## {title}")
                top = sorted(cat_entries, key=lambda x: (x.importance, x.timestamp), reverse=True)
                for e in top[: self._WIKI_TOP_N.get(cat, 50)]:
                    val_str = " ".join(str(e.value).split())[:500]
                    lines.append(f"- **{e.key}**: {val_str}")
                lines.append("")

        content = "\n".join(lines)
        self._wiki_ok = True
        if self._load_failed or self._load_skipped:
            self.logger.warning("[MEMORY] Wiki export skipped: the database load was incomplete")
            return content
        if not self._write_atomic(filepath, content):
            self._wiki_ok = False

        # Also mirror to workspace/MEMORY.md if the workspace directory exists
        if os.path.isdir(self.WS_DIR):
            if not self._write_atomic(os.path.join(self.WS_DIR, "MEMORY.md"), content):
                self._wiki_ok = False

        return content

    _WIKI_DEBOUNCE_SECONDS = 5.0
    _WIKI_RETRY_SECONDS = 30.0
    _WIKI_MAX_RETRIES = 5
    # Class-level defaults so instances built without __init__ (tests) still work.
    _wiki_lock = threading.Lock()
    _wiki_timer: threading.Timer | None = None

    def sync_markdown_wiki(self, force: bool = False):
        """Keep the Markdown wiki current without rewriting it on every single write.

        Writes are coalesced: at most one export per debounce window, performed on a
        background timer. ``force=True`` exports synchronously (used by forget).
        """
        if force or self._WIKI_DEBOUNCE_SECONDS <= 0:
            self._do_wiki_export()
            return
        self._arm_wiki_timer(self._WIKI_DEBOUNCE_SECONDS)

    def _arm_wiki_timer(self, delay: float):
        with self._wiki_lock:
            if self._wiki_timer is not None:
                return  # an export is already scheduled; it will pick up this change
            timer = threading.Timer(delay, self._wiki_timer_fire)
            timer.daemon = True
            self._wiki_timer = timer
            timer.start()

    def _wiki_timer_fire(self):
        with self._wiki_lock:
            self._wiki_timer = None
        self._do_wiki_export()

    def _do_wiki_export(self):
        ok = True
        try:
            self.export_to_markdown()
            ok = getattr(self, "_wiki_ok", True)
        except Exception as _e:
            ok = False
            self.logger.debug(f"[MEMORY] Markdown wiki sync failed: {_e}")
        if ok:
            self._wiki_retries = 0
        elif self._wiki_retries < self._WIKI_MAX_RETRIES:
            # Never leave a stale wiki behind silently: re-arm a retry (bounded).
            self._wiki_retries += 1
            self._arm_wiki_timer(self._WIKI_RETRY_SECONDS)

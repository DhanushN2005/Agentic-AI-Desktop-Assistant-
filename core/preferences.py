"""Long-term preferences Flexie learns from what you say.

Design idea adapted from Mem0 (Apache-2.0, https://github.com/mem0ai/mem0): pull short facts out of a conversation,
then for each new fact decide ADD / UPDATE (replace an outdated one) / DELETE / do NOTHING, and bring back only the
relevant ones when answering. This is a from-scratch version of just that idea: SQLite, Flexie's own language model
only as a fallback, no new package, no telemetry, nothing stored anywhere but ``data/preferences.db`` on this PC.

What it keeps: stable preferences, habits, standing instructions, and a few personal details that help (name, role,
city, language, units). What it never keeps: one-off requests, questions, anything temporary, secrets (passwords, keys,
card numbers), and sensitive categories (health, religion, politics) unless you explicitly say "remember".

You can see and delete everything in Settings > Memory, or say "forget that I prefer ...".
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass

from core.memory_manager import contains_secret, scrub
from utils.paths import data_file
from utils.sql_like import LIKE_ESCAPE, like_contains
from utils.sqlite_util import fast_connect

logger = logging.getLogger("Flexie.Preferences")

MAX_FACTS = 200
MAX_FACT_CHARS = 120
STANDING_TOPICS = {"name", "answer_length", "language", "units", "standing", "time_format", "voice", "avoid"}

# ------------------------------------------------------------------ what counts as a preference sentence
_SIGNAL = re.compile(
    r"\b(?:i\s+(?:really\s+|always\s+|usually\s+|generally\s+)?(?:prefer|like|love|hate|dislike|enjoy|can'?t\s+stand|don'?t\s+like|never|always|usually|use|work\s+as|live\s+in|am\s+(?:an?|the)\b)"
    r"|i'?m\s+(?:an?|the)\b|i'?m\s+called|my\s+(?:name|favou?rite(?:\s+\w+)?|job|role|timezone|language)\s+is|call\s+me|from\s+now\s+on|going\s+forward|in\s+(?:the\s+)?future"
    r"|please\s+always|always\s+(?:keep|use|give|reply|answer|speak|respond|show|explain|write|call|be)\b|stop\s+(?:calling|using|giving|saying)|don'?t\s+(?:call\s+me|give\s+me|use))",
    re.I)
_QUESTION = re.compile(r"^\s*(?:what|which|who|when|where|why|how|do|does|did|is|are|can|could|would|will|should)\b|\?\s*$", re.I)
_TEMPORARY = re.compile(r"\b(?:right\s+now|today|tonight|tomorrow|this\s+(?:morning|evening|afternoon|week)|at\s+the\s+moment|currently|for\s+now|just\s+now|later)\b", re.I)
_SENSITIVE = re.compile(r"\b(?:password|passcode|\bpin\b|otp|api\s*key|token|secret|credit|debit|card\s*number|cvv|aadhaar|ssn|passport|bank\s+account|account\s+number)\b", re.I)
_PERSONAL = re.compile(r"\b(?:diabet|cancer|hiv\b|depress|anxiety|pregnan|medicat|disease|religio|muslim|hindu|christian|atheist|politic|gay\b|lesbian|ethnic|caste)\w*", re.I)
_ROLES = ("engineer", "developer", "programmer", "student", "teacher", "professor", "designer", "doctor", "manager", "writer", "artist", "researcher", "founder",
          "analyst", "nurse", "lawyer", "freelancer", "consultant", "scientist", "photographer", "musician", "accountant", "architect", "entrepreneur", "teacher")
_STOP = set("a an the and or but to of in on for with at by from is are was were be been am i me my you your it its that this these those as so do does did have has had not no yes".split())

# topic -> pattern. A new fact on the same topic REPLACES the old one ("prefers long answers" replaces "prefers short answers").
_TOPICS = (
    ("name", re.compile(r"\b(?:name\s+is|call(?:ed)?\s+me|is\s+called)\b", re.I)),
    ("answer_length", re.compile(r"\b(?:short|brief|concise|detailed|long|verbose|lengthy|one[- ]sentence|bullet)\b.*\b(?:answers?|repl(?:y|ies)|responses?|explanations?)\b|\b(?:answers?|repl(?:y|ies)|responses?|explanations?)\b.*\b(?:short|brief|concise|detailed|long|verbose)\b", re.I)),
    ("language", re.compile(r"\b(?:english|hindi|tamil|telugu|malayalam|kannada|spanish|french|german|italian|japanese|korean|arabic|portuguese|russian|chinese)\b|\blanguage\b", re.I)),
    ("units", re.compile(r"\b(?:celsius|fahrenheit|kilomet\w+|miles?|metric|imperial|kg|pounds|km)\b", re.I)),
    ("time_format", re.compile(r"\b(?:12|24)[- ]?hour\b|\bam/pm\b", re.I)),
    ("location", re.compile(r"\b(?:lives?\s+in|based\s+in|located\s+in|from)\b", re.I)),
    ("role", re.compile(r"\b(?:is\s+an?|works?\s+as|am\s+an?)\s+(?:" + "|".join(_ROLES) + r")\b", re.I)),
    ("voice", re.compile(r"\b(?:voice|speak\s+(?:slower|faster|slowly|quickly)|speaking\s+speed)\b", re.I)),
    ("music", re.compile(r"\b(?:music|songs?|artists?|playlist|genre|band)\b", re.I)),
    ("editor", re.compile(r"\b(?:vs\s?code|vscode|pycharm|vim|neovim|editor|ide)\b", re.I)),
    ("browser", re.compile(r"\b(?:chrome|firefox|edge|brave|browser)\b", re.I)),
    ("avoid", re.compile(r"^(?:does\s+not\s+want|dislikes)\b", re.I)),
    ("standing", re.compile(r"^standing\s+instruction\b", re.I)),
)
_STRONG = re.compile(r"\b(?:prefer|always|never|from\s+now\s+on|going\s+forward|call\s+me|my\s+name|live\s+in|favou?rite|stop\s+\w+ing)\b", re.I)
_IMPERATIVE = r"(?:keep|use|give|reply|answer|speak|call|show|explain|respond|write|say|read|tell|be|make|add|include|skip|avoid|stop|start|open|always)"


@dataclass
class Learned:
    op: str                 # ADD | UPDATE | DELETE | NONE
    text: str
    previous: str | None = None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def topic_of(text: str) -> str | None:
    for name, rx in _TOPICS:
        if rx.search(text or ""):
            return name
    return None


def wants_to_remember(text: str) -> bool:
    return bool(re.search(r"\b(?:remember|keep\s+in\s+mind|don'?t\s+forget|note\s+that)\b", text or "", re.I))


def is_candidate(text: str) -> bool:
    """Cheap gate: first-person preference wording, not a question, not temporary, no secrets. Most utterances stop here."""
    t = (text or "").strip()
    if not t or len(t) > 300 or _QUESTION.search(t) or not _SIGNAL.search(t):
        return False
    if _TEMPORARY.search(t) or _SENSITIVE.search(t) or contains_secret(t):
        return False
    return not (_PERSONAL.search(t) and not wants_to_remember(t))


_STATEMENT_START = re.compile(
    r"^(?:(?:hey\s+)?flexi?e?[, ]+)?(?:please\s+)?(?:ok(?:ay)?[, ]+)?(?:"
    r"i\s+(?:really\s+|always\s+|usually\s+|generally\s+)?(?:prefer|like|love|hate|dislike|enjoy|can'?t\s+stand|don'?t\s+like|never|always|usually|live\s+in|am\s+an?\s+\w+)"
    r"|i'?m\s+an?\s+\w+|my\s+(?:name|favou?rite\s+\w+)\s+is|call\s+me\s+\w|from\s+now\s+on|going\s+forward|in\s+(?:the\s+)?future"
    r"|always\s+(?:keep|use|give|reply|answer|speak|respond|show|explain|write)\b|stop\s+(?:calling|using|giving|saying)\b|don'?t\s+(?:call\s+me|give\s+me|use)\b)", re.I)


def is_statement(text: str) -> bool:
    """A clean, short preference statement we can act on instead of routing as a command."""
    t = (text or "").strip()
    return bool(len(t.split()) <= 28 and _STATEMENT_START.match(t) and is_candidate(t) and extract_rules(t))


def _stem(w: str) -> str:
    w = w.lower()
    for suffix in ("ing", "es", "s"):
        if len(w) > 4 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def _key_words(text: str) -> set[str]:
    skip = {"prefer", "like", "love", "always", "never", "that", "remember", "forget", "preference", "preferences", "about", "stop", "usually"}
    return {_stem(w) for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if w not in _STOP and w not in skip and len(w) > 1}


def _clip(fragment: str) -> str:
    fragment = re.split(r"\s+(?:but|because|so\s+that|so|and\s+then|which|although|though|when|if)\s+|[.;!?]\s|,\s", fragment.strip(), maxsplit=1)[0]
    return fragment.strip(" ,.;:!\"'")


def extract_rules(text: str) -> list[dict]:
    """Deterministic extraction for the common phrasings. Returns [{"text", "op"}]; no model call."""
    t = re.sub(r"^(?:hey\s+)?flexi?e?[, ]+", "", (text or "").strip(), flags=re.I)
    t = re.sub(r"^(?:please\s+|ok(?:ay)?[, ]+|remember\s+(?:that\s+)?|note\s+that\s+)", "", t, flags=re.I).strip()
    out: list[dict] = []

    def add(fact: str, op: str = "ADD"):
        fact = re.sub(r"\s+", " ", fact).strip()
        if 6 <= len(fact) <= MAX_FACT_CHARS and fact not in [o["text"] for o in out]:
            out.append({"text": fact[0].upper() + fact[1:], "op": op})

    m = re.search(r"\b(?:call\s+me|my\s+name\s+is|i'?m\s+called)\s+([A-Za-z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*)?)", t, re.I)
    if m and not re.match(r"^(?:that|it|this|something|anything|whatever)$", m.group(1), re.I):
        add(f"Name is {m.group(1).strip().title()}")
    m = re.search(r"\bi\s+live\s+in\s+(.{2,40})", t, re.I)
    if m:
        add(f"Lives in {_clip(m.group(1)).title()}")
    m = re.search(r"\bi(?:'m|\s+am)\s+(?:an?|the)\s+([a-z][a-z \-]{2,40})", t, re.I)
    if m:
        role = _clip(m.group(1))
        if any(role.lower().endswith(r) or r in role.lower().split() for r in _ROLES):
            add(f"Is a {role.lower()}")
    m = re.search(r"\bmy\s+favou?rite\s+([a-z ]{2,24}?)\s+is\s+(.{2,50})", t, re.I)
    if m:
        add(f"Favourite {m.group(1).strip().lower()} is {_clip(m.group(2))}")
    for m in re.finditer(r"\bi\s+(?:really\s+)?(?:hate|dislike|can'?t\s+stand|don'?t\s+like)\s+(.{3,80})", t, re.I):
        add(f"Dislikes {_clip(m.group(1))}")
    for m in re.finditer(r"\bi\s+(?:really\s+)?(prefer|like|love|enjoy)\s+(.{3,80})", t, re.I):
        if re.match(r"(?:you|u|this|that|it|flexi\w*)\b", m.group(2).strip(), re.I):
            continue                                   # "I love you" is not a preference to store
        verb = "Prefers" if m.group(1).lower() == "prefer" else "Likes"
        add(f"{verb} {_clip(m.group(2))}")
    for m in re.finditer(r"\bi\s+(always|usually|generally|never)\s+(.{3,80})", t, re.I):
        add(f"{m.group(1).capitalize()} {_clip(m.group(2))}")
    m = re.search(r"\b(?:from\s+now\s+on|going\s+forward|in\s+(?:the\s+)?future|please\s+always|(?<!\bi\s)always)\s*,?\s*(" + _IMPERATIVE + r"\b.{3,100})", t, re.I)
    if m:
        add(f"Standing instruction: {_clip(m.group(1)).lower()}")
    for m in re.finditer(r"\b(?:stop|don'?t)\s+(calling|using|giving|saying)\s+(.{3,60})", t, re.I):
        add(f"Does not want: {m.group(1).lower()} {_clip(m.group(2))}")
    return out


_LLM_PROMPT = (
    "Extract LONG-TERM facts about the user from the message below: stable preferences, habits, standing instructions about how to help them, "
    "and personal details useful for assisting (name, role, city, language, units, favourite tools). "
    "Ignore one-off requests, questions, anything temporary, secrets, and health, religion or politics. "
    "Write each fact as a short third-person phrase, for example \"Prefers short answers\" or \"Lives in Chennai\". "
    'Reply with JSON only: {"facts": ["..."]}. At most 3 facts; an empty list if nothing qualifies.\n\n<message>\n%s\n</message>'
)


def extract_llm(brain, text: str) -> list[dict]:
    """Fallback for unusual phrasing: ask the configured language model. Never raises."""
    try:
        raw = brain.ask(_LLM_PROMPT % text[:300], max_tokens=120, expect_json=True)
        raw = re.sub(r"^```(?:json)?|```$", "", str(raw).strip(), flags=re.M).strip()
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        facts = data.get("facts", [])
    except Exception as e:                        # noqa: BLE001 - extraction is best effort
        logger.debug("LLM extraction skipped: %s: %s", type(e).__name__, e)
        return []
    out = []
    for f in facts[:3] if isinstance(facts, list) else []:
        f = re.sub(r"\s+", " ", str(f)).strip()
        if 6 <= len(f) <= MAX_FACT_CHARS and not re.search(r"\b(?:the user|user's)\b", f, re.I) and not _SENSITIVE.search(f) and not contains_secret(f):
            out.append({"text": f[0].upper() + f[1:], "op": "ADD"})
    return out


class PreferenceStore:
    def __init__(self, db_path: str | None = None):
        self._path = db_path or data_file("preferences.db")
        self._lock = threading.Lock()
        with self._lock:
            conn = fast_connect(self._path)
            conn.execute("""CREATE TABLE IF NOT EXISTS prefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, topic TEXT, created REAL, updated REAL,
                hits INTEGER DEFAULT 1, source TEXT DEFAULT 'rules', previous TEXT)""")
            conn.commit()
        self.on_change = None

    # ---------------------------------------------------------------- reading
    def all(self) -> list[dict]:
        with self._lock:
            rows = fast_connect(self._path).execute("SELECT id, text, topic, updated, hits, source FROM prefs ORDER BY updated DESC").fetchall()
        return [{"id": r[0], "text": r[1], "topic": r[2], "updated": r[3], "hits": r[4], "source": r[5]} for r in rows]

    def count(self) -> int:
        return len(self.all())

    def relevant(self, query: str, k: int = 6) -> list[str]:
        """Standing preferences always; everything else only when it shares a meaningful word with the question."""
        q = _words(query)
        picked, rest = [], []
        for p in self.all():
            (picked if p["topic"] in STANDING_TOPICS else rest).append(p)
        scored = sorted(((len(q & _words(p["text"])), p) for p in rest), key=lambda x: -x[0])
        picked += [p for score, p in scored if score > 0]
        return [p["text"] for p in picked[:k]]

    def prompt_block(self, query: str) -> str:
        facts = self.relevant(query)
        if not facts:
            return ""
        lines = "\n".join("- " + f.replace("\n", " ")[:MAX_FACT_CHARS] for f in facts)
        return "\n\n[What you know about this user. Follow these when relevant; do not recite the list unless asked.]\n" + lines

    # ---------------------------------------------------------------- writing
    def apply(self, fact: str, source: str = "rules") -> Learned:
        """Decide what a new fact means for what we already know (the Mem0 idea): ADD, UPDATE, DELETE or NONE."""
        raw = re.sub(r"\s+", " ", fact or "").strip()
        if not raw or contains_secret(raw) or _SENSITIVE.search(raw):      # check BEFORE masking: a masked secret no longer looks like one
            return Learned("NONE", "")
        fact = scrub(raw)[:MAX_FACT_CHARS]
        topic = topic_of(fact)
        now = time.time()
        with self._lock:
            conn = fast_connect(self._path)
            rows = conn.execute("SELECT id, text, topic FROM prefs").fetchall()
            for rid, old, _old_topic in rows:
                if old.lower() == fact.lower() or (_words(old) and len(_words(old) & _words(fact)) / max(1, len(_words(old) | _words(fact))) >= 0.8):
                    conn.execute("UPDATE prefs SET hits = hits + 1, updated = ? WHERE id = ?", (now, rid))
                    conn.commit()
                    return Learned("NONE", old)
            if topic and topic not in ("music", "editor", "browser"):
                for rid, old, old_topic in rows:
                    if old_topic == topic:
                        conn.execute("UPDATE prefs SET text = ?, previous = ?, updated = ?, source = ? WHERE id = ?", (fact, old, now, source, rid))
                        conn.commit()
                        self._changed()
                        return Learned("UPDATE", fact, old)
            if len(rows) >= MAX_FACTS:
                conn.execute("DELETE FROM prefs WHERE id = (SELECT id FROM prefs ORDER BY hits ASC, updated ASC LIMIT 1)")
            conn.execute("INSERT INTO prefs (text, topic, created, updated, source) VALUES (?, ?, ?, ?, ?)", (fact, topic, now, now, source))
            conn.commit()
        self._changed()
        return Learned("ADD", fact)

    def learn(self, text: str, brain=None, allow_llm: bool = False) -> list[Learned]:
        """Learn from one utterance. Rules first; the model only when rules found nothing and ``allow_llm``."""
        if not is_candidate(text):
            return []
        facts = extract_rules(text)
        if not facts and allow_llm and brain is not None and _STRONG.search(text):
            facts = extract_llm(brain, text)
        results = []
        for f in facts:
            if _PERSONAL.search(f["text"]) and not wants_to_remember(text):
                continue
            r = self.apply(f["text"], source="rules" if f is facts[0] and not allow_llm else "learned")
            if r.op != "NONE":
                results.append(r)
        return results

    def delete(self, pref_id: int) -> bool:
        with self._lock:
            conn = fast_connect(self._path)
            n = conn.execute("DELETE FROM prefs WHERE id = ?", (int(pref_id),)).rowcount
            conn.commit()
        if n:
            self._changed()
        return bool(n)

    def clear(self) -> int:
        with self._lock:
            conn = fast_connect(self._path)
            n = conn.execute("DELETE FROM prefs").rowcount
            conn.commit()
        if n:
            self._changed()
        return n or 0

    def forget_matching(self, text: str) -> int:
        """Used by the shared "forget" path so a forgotten preference cannot come back from here."""
        needle = (text or "").strip()
        if not needle:
            return 0
        with self._lock:
            conn = fast_connect(self._path)
            n = conn.execute(f"DELETE FROM prefs WHERE text LIKE ? ESCAPE '{LIKE_ESCAPE}'", (like_contains(needle),)).rowcount
            if not n:                                   # "forget that I prefer short answers" vs the stored "Prefers short answers"
                wanted = _key_words(needle)
                if wanted:
                    for rid, stored in conn.execute("SELECT id, text FROM prefs").fetchall():
                        if wanted <= _key_words(stored):
                            n += conn.execute("DELETE FROM prefs WHERE id = ?", (rid,)).rowcount
            conn.commit()
        if n:
            self._changed()
        return n or 0

    def _changed(self):
        cb = self.on_change
        if cb:
            try:
                cb()
            except Exception:                    # noqa: BLE001 - a listener must never break learning
                pass

    @staticmethod
    def acknowledgement(results: list[Learned]) -> str:
        """One short spoken sentence for what was just learned."""
        if not results:
            return ""
        first = results[0]
        what = first.text[0].lower() + first.text[1:] if first.text else ""
        if first.op == "UPDATE":
            return f"Updated. I'll remember: {what}."
        return f"Got it. I'll remember: {what}."

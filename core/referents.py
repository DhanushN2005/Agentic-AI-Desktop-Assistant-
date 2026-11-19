"""What "it", "that" and "the screenshot" refer to.

Flexie used to keep separate registers (last path, last screenshot, active document...) and a fixed priority
between them, so after taking a screenshot "open it" opened the older project folder. This module keeps ONE
list of the things Flexie just produced or showed, newest first, and resolves spoken references against it:

    "open it" / "show that"            -> the newest thing, whatever it is
    "open that screenshot"             -> the newest screenshot
    "open the file you just created"   -> the newest file
    "open the project"                 -> the newest project build

Pure logic, no I/O besides checking that a path still exists, so it is easy to test.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

KINDS = ("screenshot", "file", "folder", "project", "url")
MAX_ITEMS = 40
TTL = 20 * 60            # bare "it"/"that" only means something Flexie touched in the last 20 minutes
AMBIGUOUS_WINDOW = 10 * 60   # a different kind within this window: say which one we picked
CLARIFY_WINDOW = 90          # a different kind THIS close: nobody can tell which is meant, so ask

_VERBS = r"(?:open|show|launch|view|display|see|pull\s+up|bring\s+up)"
_NOUN_KINDS = {
    "screenshot": {"screenshot"}, "screenshots": {"screenshot"}, "screen shot": {"screenshot"}, "screen capture": {"screenshot"},
    "capture": {"screenshot"}, "snapshot": {"screenshot"},
    "picture": {"screenshot", "file"}, "image": {"screenshot", "file"}, "photo": {"file"}, "pic": {"screenshot", "file"},
    "file": {"file", "screenshot"}, "document": {"file"}, "doc": {"file"}, "note": {"file"}, "pdf": {"file"}, "video": {"file"},
    "script": {"file"}, "code": {"file"}, "text file": {"file"},
    "folder": {"folder", "project"}, "directory": {"folder", "project"},
    "project": {"project"}, "app": {"project"}, "application": {"project"}, "website": {"project", "url"}, "site": {"url", "project"},
    "calendar": {"project"}, "game": {"project"}, "build": {"project"},
    "link": {"url"}, "page": {"url"}, "tab": {"url"}, "url": {"url"}, "webpage": {"url"},
}
_NOUN_ALT = "|".join(sorted((re.escape(n) for n in _NOUN_KINDS), key=len, reverse=True))
_REL = r"(?:\s+(?:that\s+)?(?:you|i)\s+(?:just\s+|recently\s+)?(?:took|made|saved|created|built|generated|opened|downloaded|captured|wrote|shared|sent|showed|mentioned))?"
_TAIL = r"(?:\s+(?:again|now|please|for\s+me|right\s+now))*\s*$"
_BARE = re.compile(rf"^{_VERBS}\s+(?:me\s+)?(?P<det>it|that|this|them)(?:\s+one)?{_TAIL}")
_NOUNED = re.compile(rf"^{_VERBS}\s+(?:me\s+)?(?P<det>that|this|the|my|the\s+(?:last|latest|previous|recent)|last|latest|previous|recent)\s+(?P<noun>{_NOUN_ALT}){_REL}{_TAIL}")
_POLITE = re.compile(r"^(?:please|can\s+you|could\s+you|would\s+you|will\s+you|hey\s+flexie|flexie|ok(?:ay)?|now)\s+(?:please\s+)?", re.I)


@dataclass
class Referent:
    kind: str
    value: str            # absolute path or URL
    label: str = ""
    t: float = field(default_factory=time.time)
    seeded: bool = False      # restored from a previous run: fine to open, never offered for deletion

    def age_text(self, now: float | None = None) -> str:
        s = max(0, int((now or time.time()) - self.t))
        if s < 45:
            return "just now"
        if s < 3600:
            m = max(1, round(s / 60))
            return f"{m} minute{'s' if m != 1 else ''} ago"
        h = round(s / 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"

    def short(self) -> str:
        if self.kind == "url":
            return self.label or self.value
        return self.label or os.path.basename(self.value.rstrip("\\/")) or self.value


@dataclass
class Resolution:
    action: str | None = None      # replacement command for the orchestrator
    note: str | None = None        # one short sentence to say first (only when we had to guess)
    missing: str | None = None     # what the user asked for but Flexie has no record of ("screenshot")
    referent: Referent | None = None
    ask: str | None = None         # a short question when two kinds are equally likely
    choices: list = field(default_factory=list)


class ReferentStack:
    """Things Flexie just produced or showed, newest first."""

    def __init__(self):
        self.items: list[Referent] = []
        self.on_change = None          # called (no arguments) whenever the list changes; the dashboard listens

    def _changed(self):
        cb = self.on_change
        if cb:
            try:
                cb()
            except Exception:      # noqa: BLE001 - a listener must never break a command
                pass

    def push(self, kind: str, value: str, label: str = "", t: float | None = None, seeded: bool = False) -> Referent | None:
        if kind not in KINDS or not value:
            return None
        value = str(value)
        if kind != "url":
            value = os.path.abspath(value)
        for old in self.items:
            if old.value == value and old.kind == "project" and kind in ("folder", "file"):
                kind, label = "project", label or old.label      # the same path is the project (it opens with its browser/editor flow)
        self.items = [i for i in self.items if i.value != value]
        ref = Referent(kind, value, label, t if t is not None else time.time(), seeded)
        self.items.append(ref)
        self.items.sort(key=lambda i: i.t)
        del self.items[:-MAX_ITEMS]
        self._changed()
        return ref

    def latest(self, kinds=None, ttl: float | None = None, must_exist: bool = True, allow_seeded: bool = True) -> Referent | None:
        now = time.time()
        for ref in reversed(self.items):
            if kinds and ref.kind not in kinds:
                continue
            if ref.seeded and not allow_seeded:
                continue
            if ttl is not None and now - ref.t > ttl:
                continue
            if must_exist and ref.kind != "url" and not os.path.exists(ref.value):
                continue
            return ref
        return None

    def recent(self, n: int = 5, ttl: float | None = None) -> list[Referent]:
        now = time.time()
        out = [i for i in reversed(self.items) if (ttl is None or now - i.t <= ttl) and (i.kind == "url" or os.path.exists(i.value))]
        return out[:n]

    def forget(self, text: str) -> int:
        needle = (text or "").lower().strip()
        before = len(self.items)
        self.items = [i for i in self.items if needle not in i.value.lower() and needle not in i.label.lower()]
        if len(self.items) != before:
            self._changed()
        return before - len(self.items)

    def clear(self):
        self.items.clear()
        self._changed()

    # ---------------------------------------------------------------- resolution
    def resolve(self, command: str) -> Resolution | None:
        """Turn "open that screenshot" / "open it" into a concrete command, or None if this is not a reference."""
        c = re.sub(r"\s+", " ", (command or "").lower().strip().rstrip("?.!"))
        for _ in range(2):
            c = _POLITE.sub("", c)
        m = _NOUNED.match(c)
        if m:
            kinds = _NOUN_KINDS[m.group("noun")]
            det = m.group("det")
            has_rel = bool(re.search(r"\b(?:you|i)\s+(?:just\s+|recently\s+)?\w+$", c))
            strong = det in ("that", "this") or "last" in det or "latest" in det or "previous" in det or "recent" in det or det == "my" or has_rel
            ref = self.latest(kinds, ttl=None if strong else TTL)
            if ref is None:
                # "open the project" / "open the file" with nothing remembered: leave it to the normal routing
                return Resolution(missing=m.group("noun")) if strong else None
            return Resolution(action=self._action(ref), referent=ref)
        m = _BARE.match(c)
        if m:
            ref = self.latest(None, ttl=TTL)
            if ref is None:
                return Resolution(missing="that")
            others = [i for i in self.recent(6, ttl=AMBIGUOUS_WINDOW) if i.kind != ref.kind]
            close = [i for i in others if abs(ref.t - i.t) <= CLARIFY_WINDOW]
            if close:                                    # equally likely: ask instead of guessing
                picks, seen = [ref], {ref.kind}
                for i in close:
                    if i.kind not in seen and len(picks) < 3:
                        picks.append(i)
                        seen.add(i.kind)
                names = [f"the {self._kind_word(p)}" for p in picks]
                return Resolution(ask="Do you mean " + (", ".join(names[:-1]) + " or " + names[-1]) + "?", choices=picks)
            note = f"Opening the {self._kind_word(ref)}." if others else None
            return Resolution(action=self._action(ref), note=note, referent=ref)
        return None

    def choose(self, reply: str, choices: list):
        """Which of the offered choices a short answer picks: a Referent, "cancel", or None (not an answer)."""
        r = re.sub(r"\s+", " ", (reply or "").lower().strip().rstrip("?.!"))
        r = re.sub(r"^(?:the|that|this|my|a|an|um|uh|well|i mean|i meant|ok(?:ay)?|please)\s+", "", r)
        r = re.sub(r"\s+(?:one|please|i meant|i mean)$", "", r)
        if re.fullmatch(r"(?:cancel|never\s*mind|forget it|no|nope|none|neither|stop|nothing)", r):
            return "cancel"
        words = {"first": 0, "1": 0, "one": 0, "former": 0, "newest": 0, "latest": 0, "last": 0, "recent": 0, "second": 1, "2": 1, "two": 1, "latter": 1, "older": 1, "third": 2, "3": 2}
        if r in words and words[r] < len(choices):
            return choices[words[r]]
        for noun, kinds in sorted(_NOUN_KINDS.items(), key=lambda kv: -len(kv[0])):
            if re.fullmatch(re.escape(noun) + r"s?", r):
                for ref in choices:
                    if ref.kind in kinds:
                        return ref
        return None

    def snapshot(self, n: int = 4) -> list:
        """A small, safe view for the dashboard: kind, display name and age. Never full paths."""
        now = time.time()
        return [{"kind": i.kind, "label": i.short()[:48], "age": int(now - i.t)} for i in self.recent(n, ttl=6 * 3600)]

    @staticmethod
    def _kind_word(ref: Referent) -> str:
        return {"screenshot": "screenshot", "file": "file", "folder": "folder", "project": "project", "url": "page"}[ref.kind]

    @staticmethod
    def _action(ref: Referent) -> str:
        if ref.kind == "screenshot":
            return "show screenshot"
        if ref.kind == "project":
            return "open the project"
        if ref.kind == "url":
            return f"navigate to {ref.value}"
        return f"open_path:{ref.value}"

    # ---------------------------------------------------------------- self-awareness
    def describe(self, n: int = 4) -> str:
        items = self.recent(n, ttl=6 * 3600)
        if not items:
            return "I haven't made or opened anything in this session yet."
        words = {"screenshot": "a screenshot", "file": "the file", "folder": "the folder", "project": "the project", "url": "the page"}
        parts = [f"{words[i.kind]} {i.short()} ({i.age_text()})" for i in items]
        return "Most recently I worked with " + "; ".join(parts) + ". Say 'open it' for the newest one."

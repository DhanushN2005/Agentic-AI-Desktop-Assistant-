"""Clause splitting for multi-step requests.

Splitting a request on every "and" or comma breaks ordinary phrases ("rock and roll",
"salt and pepper", quoted text to write) and used to lowercase the user's text. This splitter:

  * never splits inside quotes
  * never splits inside well-known "X and Y" idioms
  * splits on "and" / commas only when the next words start a NEW command (a command verb)
  * always splits on unambiguous sequencing words (then, after that, afterwards, finally)
  * does not split a compound infinitive ("to sort and print the list")
  * preserves the user's original text (case, paths, punctuation)
"""
from __future__ import annotations

import re

COMMAND_VERBS = frozenset("""
open close launch start stop run execute play pause resume skip search find look lookup google send
write create make build generate delete remove erase rename move copy paste save set turn switch
increase decrease raise lower mute unmute take capture read show tell remind call email text message
go navigate click type fill press download upload install uninstall update summarize summarise
translate convert calculate add check schedule book order buy pay export import print scan restart
shutdown lock unlock sleep wake enable disable bookmark share post browse visit watch listen ask
explain describe list count compare git commit push pull merge debug fix test refactor deploy
research please also
wipe nuke uninstall shred trash overwrite clear erase kill terminate reply forward wire donate
tweet publish deploy withdraw transfer sign log reboot purge destroy drop truncate
mail dm whatsapp
""".split())

# Sequencers that always start a new step when real text follows them.
_ALWAYS_SPLIT = ("and then", "after that", "afterwards", "then", "finally")
# "next" is only a sequencer when a command verb follows ("... next play jazz"), not in "next song".
_VERB_GATED = ("and", "next", "also", "plus")

IDIOMS = (
    "rock and roll", "salt and pepper", "black and white", "bread and butter", "pros and cons",
    "ladies and gentlemen", "mac and cheese", "macaroni and cheese", "trial and error",
    "back and forth", "up and down", "rise and fall", "law and order", "fish and chips",
    "drum and bass", "more and more", "over and over", "rhythm and blues", "r and b",
    "tom and jerry", "romeo and juliet", "pride and prejudice", "war and peace",
    "arts and crafts", "health and safety", "terms and conditions", "q and a", "r and d",
    "research and development", "copy and paste", "cut and paste", "drag and drop",
    "find and replace", "search and rescue", "on and off", "in and out", "now and then",
)

FILLERS = frozenset({"please", "ok", "okay", "also", "and", "then", "next", "finally", "hey", "flexie"})

_QUOTE_RE = re.compile(
    r'"[^"\n]*"'                       # "double"
    r"|“[^”\n]*”"       # curly double
    r"|‘[^’\n]*’"       # curly single
    r"|(?<![\w])'[^'\n]*'(?![\w])"     # 'single' (not apostrophes inside words)
)
_IDIOM_RE = re.compile("|".join(r"\b" + re.escape(p) + r"\b" for p in IDIOMS), re.I)
_SEP_RE = re.compile(
    r"\s*(?:,|;)\s*(?:(?P<c1>and then|and|then|after that|finally)\s+)?"
    r"|\s+(?P<c2>and then|after that|afterwards|then|finally|and|next|also|plus)\s+",
    re.I,
)
_WORD_RE = re.compile(r"[A-Za-z']+")
_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")


def _mask(text: str) -> tuple[str, list[str]]:
    saved: list[str] = []

    def stash(match: re.Match) -> str:
        saved.append(match.group(0))
        return _PLACEHOLDER.format(len(saved) - 1)

    text = _QUOTE_RE.sub(stash, text)
    text = _IDIOM_RE.sub(stash, text)
    return text, saved


def _unmask(text: str, saved: list[str]) -> str:
    # Placeholders can nest (an idiom inside masked text is not possible, but be safe).
    for _ in range(3):
        new = _PLACEHOLDER_RE.sub(lambda m: saved[int(m.group(1))], text)
        if new == text:
            break
        text = new
    return text


def _next_word(masked: str, pos: int) -> str:
    match = _WORD_RE.search(masked, pos)
    return match.group(0).lower() if match else ""


def split_clauses(text: str) -> list[str]:
    """Split a request into steps; always returns at least one element for non-empty input."""
    if not text or not text.strip():
        return []
    masked, saved = _mask(text)
    parts: list[str] = []
    start = 0
    for m in _SEP_RE.finditer(masked):
        word = (m.group("c2") or m.group("c1") or "").lower()
        following = _next_word(masked, m.end())
        if not following:
            continue  # trailing separator: nothing to start a new step
        sequencer = word in _ALWAYS_SPLIT
        if not sequencer:
            # "and"/"next"/bare comma: only a new step if a command verb comes next
            if following not in COMMAND_VERBS:
                continue
            # compound infinitive: "to sort and print the list" stays one step
            before = masked[start:m.start()].rstrip()
            if re.search(r"\bto\s+\w+$", before, re.I):
                continue
        parts.append(masked[start:m.start()])
        start = m.end()
    parts.append(masked[start:])

    out: list[str] = []
    for part in parts:
        restored = _trim_sequencers(_unmask(part, saved).strip(" \t\r\n,;"))
        if restored and restored.lower() not in FILLERS:
            out.append(restored)
    return out or [text.strip()]


_LEAD_RE = re.compile(r"^(?:and then|after that|afterwards|then|finally|and)\s+", re.I)
_TRAIL_RE = re.compile(r"\s+(?:and then|after that|afterwards|then|finally|and)$", re.I)


def _trim_sequencers(text: str) -> str:
    """Drop a dangling sequencer left at either end ("open chrome and", "then open chrome")."""
    previous = None
    while previous != text:
        previous = text
        text = _TRAIL_RE.sub("", _LEAD_RE.sub("", text.strip())).strip(" 	,;")
    return text


def has_multiple_actions(text: str) -> bool:
    return len(split_clauses(text)) > 1

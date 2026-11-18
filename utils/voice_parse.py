"""Shared parsing of spoken times, durations and numbers.

Used by reminders, alarms/timers, notifications and the pomodoro handler so
they all agree on what "5pm", "in 1.5 hours" or "2 hours 30 minutes" mean.

All functions take the ORIGINAL (or lowercased) text; matching is
case-insensitive and nothing here mutates the caller's payload.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta


class TimeParseError(ValueError):
    """A time phrase was found but its values are impossible (e.g. 25:00)."""


_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SPECIAL = {"a": 1, "an": 1, "couple": 2, "dozen": 12, "half": 0.5}

_WORD_NUM = r"(?:" + "|".join(sorted(list(_ONES) + list(_TENS), key=len, reverse=True)) + r")"
# "twenty five", "twenty-five", "five", "a", "an", "a couple of" are accepted
_NUM_TOKEN = (
    r"(?:\d+(?:\.\d+)?|" + _WORD_NUM + r"(?:[\s-]" + _WORD_NUM + r")?|an?(?:\s+couple\s+of)?|half)"
)
_UNIT = (
    r"(?P<unit>hours?|hrs?|minutes?|mins?|seconds?|secs?)\b"
)
_DUR_RE = re.compile(r"(?<![\w.:])(?P<num>" + _NUM_TOKEN + r")\s*" + _UNIT, re.IGNORECASE)
_HALF_HOUR_RE = re.compile(r"\bhalf\s+an?\s+hour\b", re.IGNORECASE)
_AND_HALF_RE = re.compile(
    r"(?<![\w.])(?P<num>\d+(?:\.\d+)?|" + _WORD_NUM + r"|an?)\s+hours?\s+and\s+a\s+half\b",
    re.IGNORECASE,
)


def parse_number(text: str):
    """Parse a number from digits or words ('5', '1.5', 'five', 'twenty five',
    'a couple', 'a dozen').  Returns int/float or None."""
    if text is None:
        return None
    s = str(text).strip().lower()
    if not s:
        return None
    m = re.search(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?|(?<![\w.])-?\.\d+", s)
    # prefer a real digit number only if the text is mostly numeric
    if m and re.fullmatch(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\.\d+", s.strip()):
        val = float(m.group(0).replace(",", ""))
        return int(val) if val.is_integer() else val
    s = re.sub(r"\ban?\s+(?=couple|dozen)", "", s)
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", s.replace("-", " "))
    total = 0.0
    found = False
    for tok in tokens:
        if tok in _ONES:
            total += _ONES[tok]
            found = True
        elif tok in _TENS:
            total += _TENS[tok]
            found = True
        elif tok == "hundred" and found:
            total = total * 100 if total else 100
        elif tok in _SPECIAL and tok in ("couple", "dozen"):
            total += _SPECIAL[tok]
            found = True
        elif tok in ("a", "an") and not found:
            total += 1
            found = True
        elif re.fullmatch(r"\d+(?:\.\d+)?", tok):
            total += float(tok)
            found = True
        elif tok in ("of", "and"):
            continue
        elif found:
            break
    if not found:
        if m:
            val = float(m.group(0).replace(",", ""))
            return int(val) if val.is_integer() else val
        return None
    return int(total) if float(total).is_integer() else total


def _num_value(tok: str) -> float:
    tok = tok.strip().lower()
    if tok.startswith("a couple"):
        return 2.0
    if tok in ("a", "an"):
        return 1.0
    if tok == "half":
        return 0.5
    if re.fullmatch(r"\d+(?:\.\d+)?", tok):
        return float(tok)
    val = parse_number(tok)
    return float(val) if val is not None else 0.0


def parse_duration(text: str):
    """Total duration in seconds found in text, or None.

    '1.5 hours' -> 5400, '2 hours 30 minutes' -> 9000, 'an hour' -> 3600,
    'a minute' -> 60, '45 seconds' -> 45, 'half an hour' -> 1800,
    'an hour and a half' -> 5400.
    """
    if not text:
        return None
    s = str(text)
    total = 0.0
    found = False

    def _consume(pattern, fn):
        nonlocal s, total, found
        def _sub(m):
            nonlocal total, found
            total += fn(m)
            found = True
            return " "
        s = pattern.sub(_sub, s)

    _consume(_HALF_HOUR_RE, lambda m: 1800.0)
    _consume(_AND_HALF_RE, lambda m: (_num_value(m.group("num")) + 0.5) * 3600)

    def _unit_secs(m):
        n = _num_value(m.group("num"))
        u = m.group("unit").lower()
        if u.startswith("h"):
            return n * 3600
        if u.startswith("m"):
            return n * 60
        return n

    _consume(_DUR_RE, _unit_secs)
    if not found:
        return None
    return int(total) if float(total).is_integer() else total


def format_duration(seconds) -> str:
    """'1 minute 30 seconds', '2 hours 30 minutes', '45 seconds', '1 hour'."""
    total = int(round(seconds))
    if total <= 0:
        return "0 seconds"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    return " ".join(parts)


# ---------------------------------------------------------------- clock times
_AMPM = r"(?P<ampm>[ap])\.?m\.?"
_CLOCK_AT = re.compile(
    r"\bat\s+(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?:" + _AMPM + r")?(?![\d:])",
    re.IGNORECASE,
)
_CLOCK_AMPM = re.compile(
    r"(?<![\w:.])(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*" + _AMPM + r"(?!\w)",
    re.IGNORECASE,
)
_CLOCK_24 = re.compile(r"(?<![\w:.])(?P<h>\d{1,2}):(?P<m>\d{2})(?![\d:])")
_NOON = re.compile(r"\b(?:at\s+)?noon\b|\b(?:at\s+)?midday\b", re.IGNORECASE)
_MIDNIGHT = re.compile(r"\b(?:at\s+)?midnight\b", re.IGNORECASE)
_TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
_IN_DUR = re.compile(r"\bin\s+(?:about\s+|around\s+)?(?=" + _NUM_TOKEN + r"\s*" + _UNIT + r"|half\s+an?\s+hour)",
                     re.IGNORECASE)


def _clock_fields(m):
    """Return (hour, minute) 24h from a regex match or raise TimeParseError."""
    hour = int(m.group("h"))
    minute = int(m.group("m") or 0)
    ampm = (m.groupdict().get("ampm") or "").lower()
    if minute > 59:
        raise TimeParseError(f"{minute} is not a valid minute.")
    if ampm:
        if not 1 <= hour <= 12:
            raise TimeParseError(f"{hour} is not a valid hour for am/pm.")
        if ampm == "p" and hour < 12:
            hour += 12
        elif ampm == "a" and hour == 12:
            hour = 0
    elif hour > 23:
        raise TimeParseError(f"{hour}:{minute:02d} is not a valid time.")
    return hour, minute


def _find_clock(text: str):
    """Locate an absolute clock time; returns (hour, minute, span) or None."""
    if _NOON.search(text):
        m = _NOON.search(text)
        return 12, 0, m.span()
    if _MIDNIGHT.search(text):
        m = _MIDNIGHT.search(text)
        return 0, 0, m.span()
    for rx in (_CLOCK_AMPM, _CLOCK_AT, _CLOCK_24):
        m = rx.search(text)
        if m:
            h, mi = _clock_fields(m)
            return h, mi, m.span()
    return None


def time_phrase_spans(text: str):
    """Spans of time phrases (for stripping them from a task description)."""
    spans = []
    for m in _DUR_RE.finditer(text):
        # include a leading 'in [about]'
        start = m.start()
        pre = re.search(r"\bin\s+(?:about\s+|around\s+)?$", text[:start], re.IGNORECASE)
        if pre:
            start = pre.start()
        spans.append((start, m.end()))
    for rx in (_HALF_HOUR_RE, _AND_HALF_RE, _TOMORROW, _NOON, _MIDNIGHT):
        spans.extend(m.span() for m in rx.finditer(text))
    clock = None
    try:
        clock = _find_clock(text)
    except TimeParseError:
        clock = None
    if clock:
        a, b = clock[2]
        pre = re.search(r"\bat\s+$", text[:a], re.IGNORECASE)
        if pre:
            a = pre.start()
        spans.append((a, b))
    return spans


def remove_time_phrases(text: str) -> str:
    """Text with every recognised time phrase removed and spaces collapsed."""
    spans = sorted(time_phrase_spans(text))
    out, pos = [], 0
    for a, b in spans:
        if a < pos:
            b2 = max(b, pos)
            pos = b2
            continue
        out.append(text[pos:a])
        pos = b
    out.append(text[pos:])
    res = re.sub(r"\s+", " ", "".join(out)).strip()
    return re.sub(r"\s+([,.;])", r"\1", res)


def local_timestamp(dt: datetime) -> float:
    return dt.timestamp()


def seconds_until(target: datetime, now: datetime) -> float:
    """Elapsed seconds from now to target, correct across DST changes for
    naive local datetimes (uses real timestamps rather than wall-clock
    subtraction).  For aware datetimes plain subtraction is exact."""
    if target.tzinfo is not None or now.tzinfo is not None:
        return (target - now).total_seconds()
    try:
        return target.timestamp() - now.timestamp()
    except (OverflowError, OSError, ValueError):
        return (target - now).total_seconds()


def parse_time(text: str, now: datetime | None = None):
    """Resolve a spoken time to a datetime strictly after `now`.

    Supports 'in 10 minutes', 'in an hour', 'in 1.5 hours', 'in 2 hours 30
    minutes', 'in 45 seconds', '5pm', '7 am', '5:30 pm', 'at 17:30', 'at 9',
    'noon', 'midnight', 'tomorrow', 'tomorrow at 9'.  Absolute times roll to
    tomorrow when already past (wall-clock, so DST-safe).  Returns None when
    no time is present; raises TimeParseError for impossible values.
    """
    if not text:
        return None
    now = now or datetime.now()
    s = str(text)

    # Relative: "in <duration>"
    if _IN_DUR.search(s):
        secs = parse_duration(s)
        if secs is not None and secs > 0:
            if now.tzinfo is None:
                try:
                    return datetime.fromtimestamp(now.timestamp() + secs)
                except (OverflowError, OSError, ValueError):
                    pass
            return now + timedelta(seconds=secs)

    clock = _find_clock(s)
    tomorrow = bool(_TOMORROW.search(s))
    if clock:
        hour, minute, _ = clock
        day = now.date() + timedelta(days=1 if tomorrow else 0)
        target = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(
            hour=hour, minute=minute)
        if target <= now:
            target = datetime.combine(
                target.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo
            ).replace(hour=hour, minute=minute)
        return target
    if tomorrow:
        # bare 'tomorrow' -> 9:00 the next day
        day = now.date() + timedelta(days=1)
        return datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo).replace(hour=9)
    return None


_WAKE_RE = re.compile(r"^\s*(?:hey\s+|ok\s+|okay\s+)?(?:flexie|flexi)\b[\s,.:;-]*", re.IGNORECASE)


def strip_wake(text: str) -> str:
    """Remove a leading wake word ('hey flexie,') keeping the rest verbatim."""
    return _WAKE_RE.sub("", text or "", count=1).strip()


def is_relative(text: str) -> bool:
    """True when the time is spoken as an offset ('in 10 minutes')."""
    return bool(text) and bool(_IN_DUR.search(text)) and parse_duration(text) is not None


def extract_time_phrase(text: str) -> str:
    """The time-related words of `text` (e.g. 'at 7 pm', 'tomorrow'), joined."""
    spans = sorted(time_phrase_spans(text or ""))
    parts, last_end = [], -1
    for a, b in spans:
        if a < last_end:
            continue
        parts.append(text[a:b])
        last_end = b
    return " ".join(parts)

import re
from datetime import datetime

from utils.config import Config
from utils.voice_parse import (
    TimeParseError,
    format_duration,
    is_relative,
    parse_time,
    remove_time_phrases,
    seconds_until,
    strip_wake,
)


def _now() -> datetime:
    """Current local time (patched in tests)."""
    return datetime.now()


def _parse_time(text: str, now: datetime | None = None):
    """Absolute target datetime for a spoken time, or None (shared parser)."""
    return parse_time(text, now or _now())


def _parse_minutes(text: str, now: datetime | None = None) -> float:
    """Minutes from now until the time spoken in `text` (default if none)."""
    now = now or _now()
    target = parse_time(text, now)
    if target is None:
        return float(Config.DEFAULT_REMINDER_MINUTES)
    return max(seconds_until(target, now), 0.0) / 60.0


_PREFIXES = [
    r"^remind me to\s+",
    r"^remind me\s+",
    r"^set (?:a )?reminder (?:to|for)\s+",
    r"^set (?:an )?alarm (?:to|for)\s+",
    r"^remember to\s+",
    r"^schedule (?:a )?reminder (?:to|for)\s+",
    r"^set a reminder\s+",
]


def _extract_task(text: str) -> str:
    """Extract the reminder task from text, preserving its original case."""
    task = text.strip()
    for prefix in _PREFIXES:
        task = re.sub(prefix, "", task, flags=re.IGNORECASE).strip()
    task = remove_time_phrases(task)
    task = re.sub(r"\s+", " ", task).strip()
    # dangling connectors left behind by removed time phrases
    task = re.sub(r"\s+(?:at|in|on|by|for|and)$", "", task, flags=re.IGNORECASE).strip()
    task = re.sub(r"^(?:to|that|and|at|in|on)\s+", "", task, flags=re.IGNORECASE).strip()
    return task.strip(" ,.;")


def _speak_reminders(orch):
    pending = orch.memory.list_reminders()
    if not pending:
        orch.speak("You have no pending reminders.")
    else:
        parts = ", ".join(f"'{t}'" for t in pending)
        orch.speak(f"You have {len(pending)} reminder(s): {parts}.")
    return True


def _describe(target: datetime, now: datetime, secs: float, relative: bool) -> str:
    if relative:
        return f"in {format_duration(secs)}"
    time_str = target.strftime(Config.TIME_FORMAT)
    day_delta = (target.date() - now.date()).days
    if day_delta == 1:
        return f"tomorrow at {time_str}"
    if day_delta > 1:
        return f"on {target.strftime('%B %d')} at {time_str}"
    return f"at {time_str}"


def handle_remind(orch, c):
    original = strip_wake(c)
    text = original.lower()
    if any(x in text for x in ["list reminders", "show reminders", "what reminders", "list my reminders", "pending reminders"]):
        return _speak_reminders(orch)

    now = _now()
    try:
        target = parse_time(original, now)
    except TimeParseError as e:
        orch.speak(f"That doesn't look like a valid time. {e}")
        return True
    task = _extract_task(original)

    if not task:
        orch.speak("What should I remind you about?")
        return True

    if target is None:
        secs = float(Config.DEFAULT_REMINDER_MINUTES) * 60
        when = f"in {format_duration(secs)}"
    else:
        secs = max(seconds_until(target, now), 0.0)
        relative = is_relative(original)
        when = _describe(target, now, secs, relative)

    # Single mechanism: the orchestrator's DB poller fires due reminders.
    # (No sleeping thread here - that spoke every reminder twice.)
    orch.memory.add_reminder(task, secs / 60.0)

    orch.speak(f"Got it. I'll remind you {when} to {task}.")
    return True


def handle_list_reminders(orch):
    return _speak_reminders(orch)

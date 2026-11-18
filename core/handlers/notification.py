import re
import threading
from datetime import datetime

from utils.config import Config
from utils.voice_parse import (
    TimeParseError,
    parse_time,
    remove_time_phrases,
    seconds_until,
    strip_wake,
)


def _now() -> datetime:
    """Current local time (patched in tests)."""
    return datetime.now()


def _parse_notify_time(cmd: str, now: datetime | None = None):
    """Seconds until the notification time in `cmd`, or None if no time given.

    Raises TimeParseError for impossible times such as 'at 25:00'.  Uses the
    shared parser, so midnight rollover on the 30th/31st and DST are handled.
    """
    now = now or _now()
    target = parse_time(cmd, now)
    if target is None:
        return None
    return int(max(seconds_until(target, now), 0))


_CMD_PREFIX = re.compile(
    r"\b(?:notify me|set (?:a )?notification|remind me|notification)\b", re.IGNORECASE
)


def _extract_notify_message(cmd: str):
    """Extract the notification message, preserving case.

    Only connector words at the START/END of the message are dropped, so
    'go to the gym' and 'talk about taxes' stay intact.
    """
    msg = _CMD_PREFIX.sub(" ", cmd, count=1)
    msg = remove_time_phrases(msg)
    prev = None
    while prev != msg:
        prev = msg
        msg = re.sub(r"^[\s,.:;-]*(?:about|to|that|for|at|in|on|and)\b[\s,.:;-]*", "", msg, flags=re.IGNORECASE)
        msg = re.sub(r"[\s,.:;-]*\b(?:at|in|on|for|and)[\s,.:;-]*$", "", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\s+", " ", msg).strip()
    msg = re.sub(r"^[,.\s]+|[,.\s]+$", "", msg)
    return msg if msg else None


def _fire_notification(orch, message):
    """Callback to fire when notification timer completes."""
    orch.speak(f"Notification: {message}")


def handle_notification(orch, c):
    """Handle notification commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    try:
        seconds = _parse_notify_time(original)
    except TimeParseError as e:
        response = f"That doesn't look like a valid time. {e}"
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True
    message = _extract_notify_message(original)

    if seconds is not None and message:
        timer = threading.Timer(seconds, lambda: _fire_notification(orch, message))
        timer.daemon = True
        timer.start()
        response = f"Notification set: {message}"
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if seconds is not None and not message:
        # No pending-action consumer exists for a follow-up, so ask for the
        # full command again instead of leaving a dangling flag.
        response = "What should I notify you about? Say it again with the message, like 'notify me in 10 minutes to call mom'."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if seconds is None and message:
        timer = threading.Timer(Config.DEFAULT_NOTIFY_TIMEOUT, lambda: _fire_notification(orch, message))
        timer.daemon = True
        timer.start()
        response = f"Notification set for {Config.DEFAULT_NOTIFY_TIMEOUT // 60} minutes: {message}"
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    response = "Say 'notify me in 10 minutes to call mom' or 'notify me at 5:52 about the meeting'."
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

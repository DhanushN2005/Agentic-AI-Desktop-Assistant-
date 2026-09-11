import re
import threading
from datetime import datetime
from utils.config import Config


def _parse_notify_time(cmd: str):
    """Parse notification time from text like '5:52', '5 PM', 'in 10 minutes'."""
    m = re.search(r"in\s+(\d+)\s*(minute|min|hour|hr|second|sec)", cmd)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("hour") or unit == "hr":
            return value * 3600
        elif unit.startswith("minute") or unit == "min":
            return value * 60
        else:
            return value

    m = re.search(r"(?:at|on)\s+(\d{1,2})\s*[:\s]\s*(\d{2})\s*(am|pm)?", cmd)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = m.group(3)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm and ampm.lower() == "am" and hour == 12:
            hour = 0
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target = target.replace(day=now.day + 1)
        return int((target - now).total_seconds())

    m = re.search(r"\bat\s+(\d{1,2})\s*(am|pm)?", cmd)
    if m:
        hour = int(m.group(1))
        ampm = m.group(2)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        elif ampm and ampm.lower() == "am" and hour == 12:
            hour = 0
        now = datetime.now()
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target.replace(day=now.day + 1)
        return int((target - now).total_seconds())

    return None


def _extract_notify_message(cmd: str):
    """Extract the notification message from the command."""
    msg = re.sub(r"\b(notify me|set (?:a )?notification|remind me)\b", "", cmd, flags=re.IGNORECASE)
    msg = re.sub(r"\b(?:at|on|in|for)\s+\d{1,2}[:\s]\d{2}\s*(?:am|pm)?\b", "", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\b(?:at|on|in|for)\s+\d{1,2}\s*(?:am|pm)?\b", "", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\b(?:in)\s+\d+\s*(?:minute|min|hour|hr|second|sec)s?\b", "", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\b(?:about|to)\b", "", msg, flags=re.IGNORECASE)
    msg = re.sub(r"\s+", " ", msg).strip()
    msg = re.sub(r"^[,.\s]+|[,.\s]+$", "", msg)
    return msg if msg else None


def _fire_notification(orch, message):
    """Callback to fire when notification timer completes."""
    orch.speak(f"Notification: {message}")


def handle_notification(orch, c):
    """Handle notification commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    seconds = _parse_notify_time(cmd)
    message = _extract_notify_message(cmd)

    if seconds and message:
        timer = threading.Timer(seconds, lambda: _fire_notification(orch, message))
        timer.daemon = True
        timer.start()
        response = f"Notification set: {message}"
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if seconds and not message:
        orch.ctx.set_pending_action("waiting_for_notify_message")
        orch.ctx.set("notify_seconds", seconds)
        response = "What should I notify you about?"
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if not seconds and message:
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

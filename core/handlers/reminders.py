import re
import time
import threading
from datetime import datetime, timedelta
from utils.config import Config


def _parse_time(text: str):
    """Parse time from text like '5 pm', '14:00', 'in 10 minutes'."""
    now = datetime.now()

    # Try "at 5 pm", "at 5:30 pm", "at 14:00"
    m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    # Try "in 10 minutes", "in 2 hours"
    m = re.search(r"in\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*(min(?:ute)?s?|hrs?|hour(?:s)?|sec(?:ond)?s?)", text)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("h"):
            return now + timedelta(hours=val)
        elif unit.startswith("s"):
            return now + timedelta(seconds=val)
        else:
            return now + timedelta(minutes=val)

    if re.search(r"in\s+(?:a|one)\s+minute", text):
        return now + timedelta(minutes=1)
    if re.search(r"in\s+(?:an|one)\s+hour", text):
        return now + timedelta(hours=1)

    return None


def _extract_task(text: str) -> str:
    """Extract the reminder task from text."""
    task = text.lower().strip()
    # Remove common prefixes
    prefixes = [
        r"^remind me to\s+",
        r"^remind me\s+",
        r"^set (?:a )?reminder (?:to|for)\s+",
        r"^set (?:an )?alarm (?:to|for)\s+",
        r"^remember to\s+",
        r"^schedule (?:a )?reminder (?:to|for)\s+",
        r"^set a reminder\s+",
    ]
    for prefix in prefixes:
        task = re.sub(prefix, "", task).strip()
    task = re.sub(r"^(?:to|that)\s+", "", task).strip()
    # Remove time phrases
    task = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", task).strip()
    task = re.sub(r"\bin\s+(?:about\s+)?\d+(?:\.\d+)?\s*(?:min(?:ute)?s?|hrs?|hour(?:s)?|sec(?:ond)?s?)\b", "", task).strip()
    task = re.sub(r"\bin\s+(?:a|one)\s+(?:minute|hour)\b", "", task).strip()
    task = re.sub(r"\s+", " ", task).strip()
    # Clean leading connector words
    task = re.sub(r"^(?:to|that|and)\s+", "", task).strip()
    return task


def _parse_minutes(text: str) -> float:
    """Parse minutes from text."""
    # Try "in 10 minutes"
    m = re.search(r"in\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*(min(?:ute)?s?|hrs?|hour(?:s)?|sec(?:ond)?s?)", text)
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("h"):
            return val * 60
        elif unit.startswith("s"):
            return val / 60
        return val
    if re.search(r"in\s+(?:a|one)\s+minute", text):
        return 1.0
    if re.search(r"in\s+(?:an|one)\s+hour", text):
        return 60.0
    return Config.DEFAULT_REMINDER_MINUTES  # default


def _speak_reminders(orch):
    pending = orch.memory.list_reminders()
    if not pending:
        orch.speak("You have no pending reminders.")
    else:
        parts = ", ".join(f"'{t}'" for t in pending)
        orch.speak(f"You have {len(pending)} reminder(s): {parts}.")
    return True


def handle_remind(orch, c):
    text = c.lower().strip()
    if any(x in text for x in ["list reminders", "show reminders", "what reminders", "list my reminders", "pending reminders"]):
        return _speak_reminders(orch)

    target = _parse_time(text)
    task = _extract_task(text)

    if not task:
        orch.speak("What should I remind you about?")
        return True

    minutes = _parse_minutes(text)

    # Store in database
    orch.memory.add_reminder(task, minutes)

    # Schedule the reminder to actually speak
    delay = minutes * 60
    def _trigger():
        time.sleep(delay)
        orch.speak(f"Reminder: You asked me to remind you to {task}.")
        orch.memory.mark_reminder_done(task)

    t = threading.Thread(target=_trigger, daemon=True)
    t.start()

    # Check if it's a relative time ("in X minutes") or absolute ("at 5 PM")
    is_relative = re.search(r"\bin\s+(?:about\s+)?\d+", text)
    if is_relative:
        mins = int(minutes)
        if minutes == 60:
            orch.speak(f"Got it. I'll remind you in 1 hour to {task}.")
        elif minutes == 1:
            orch.speak(f"Got it. I'll remind you in 1 minute to {task}.")
        else:
            orch.speak(f"Got it. I'll remind you in {mins} minutes to {task}.")
    elif target:
        time_str = target.strftime(Config.TIME_FORMAT)
        orch.speak(f"Got it. I'll remind you at {time_str} to {task}.")
    else:
        orch.speak(f"Got it. I'll remind you in {Config.DEFAULT_REMINDER_MINUTES:.0f} minutes to {task}.")
    return True


def handle_list_reminders(orch):
    return _speak_reminders(orch)

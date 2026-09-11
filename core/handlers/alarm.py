import re
from datetime import datetime
from utils.config import Config


def _parse_duration(cmd: str):
    """Parse duration from text like '30 seconds', '10 minutes', '1 hour'."""
    m = re.search(r"(\d+)\s*(second|minute|hour|sec|min|hr)", cmd)
    if m:
        value = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("hour") or unit == "hr":
            return value * 3600
        elif unit.startswith("minute") or unit == "min":
            return value * 60
        else:
            return value
    return None


def handle_alarm(orch, c):
    """Handle alarm and timer commands with multi-turn support."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if orch.ctx.pending_action == "waiting_for_timer_duration":
        orch.ctx.clear_pending_action()
        seconds = _parse_duration(cmd)
        if seconds:
            response = orch.alarm.set_timer(seconds, "Timer")
            orch.ctx.update(last_response=response, query=c)
            orch.speak(response)
            return True
        else:
            orch.speak("I didn't catch that. Try '30 seconds' or '10 minutes'.")
            return True

    if any(x in cmd for x in ["what time", "tell me the time", "tell me current time",
                                "whats the time", "what's the time", "current time",
                                "what time is it", "time is it"]):
        now = datetime.now()
        response = f"It's {now.strftime(Config.TIME_FORMAT)}."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if any(w in cmd for w in ["set alarm", "alarm for", "wake me"]):
        time_match = re.search(r"(?:alarm|wake me)\s+(?:at|for)\s+(.+?)(?:\s+(?:to|for)\s+(.+))?$", cmd)
        if time_match:
            time_str = time_match.group(1).strip()
            label = time_match.group(2).strip() if time_match.group(2) else "Alarm"
            response = orch.alarm.set_alarm(time_str, label)
        else:
            response = "Say 'set alarm for 7:30 AM'."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if any(w in cmd for w in ["set timer", "timer for", "countdown", "count down"]):
        seconds = _parse_duration(cmd)
        if seconds:
            response = orch.alarm.set_timer(seconds, "Timer")
        else:
            orch.ctx.set_pending_action("waiting_for_timer_duration")
            response = "How long? Say '30 seconds' or '10 minutes'."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if any(w in cmd for w in ["list alarm", "list timer", "active alarm", "active timer"]):
        response = orch.alarm.list_alarms() + " " + orch.alarm.list_timers()
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    response = "Say 'set alarm for 7 AM' or 'timer for 10 minutes'."
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

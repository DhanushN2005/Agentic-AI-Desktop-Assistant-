import re
from datetime import datetime

from utils.config import Config
from utils.voice_parse import (
    TimeParseError,
    extract_time_phrase,
    parse_duration,
    parse_time,
    remove_time_phrases,
    strip_wake,
)


def _parse_duration(cmd: str):
    """Duration in seconds from '30 seconds', '1.5 hours', '2 hours 30 minutes'."""
    return parse_duration(cmd)


def _word(cmd: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", cmd) for w in words)


_LEAD = re.compile(
    r"^(?:please\s+)?(?:set\s+(?:an?\s+|my\s+)?alarm|wake\s+me(?:\s+up)?|alarm)\b[\s,]*",
    re.IGNORECASE,
)


def _alarm_label(original: str) -> str:
    rest = remove_time_phrases(original)
    rest = _LEAD.sub("", rest.strip()).strip()
    prev = None
    while prev != rest:
        prev = rest
        rest = re.sub(r"^(?:for|at|to|called|named|labeled|labelled|on|and)\b[\s,:]*", "", rest, flags=re.IGNORECASE).strip()
    return rest.strip(" ,.") or "Alarm"


def handle_alarm(orch, c):
    """Handle alarm and timer commands with multi-turn support."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()

    if orch.ctx.pending_action == "waiting_for_timer_duration":
        orch.ctx.clear_pending_action()
        seconds = _parse_duration(original)
        if seconds:
            response = orch.alarm.set_timer(seconds, "Timer")
            orch.ctx.update(last_response=response, query=c)
            orch.speak(response)
            return True
        else:
            orch.speak("I didn't catch that. Try '30 seconds' or '10 minutes'.")
            return True

    if re.search(r"\bdate\b|\bwhat\s+day\b|\bwhich\s+day\b", cmd) and not _word(cmd, "alarm", "timer"):
        now = datetime.now()
        response = f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if (
        any(x in cmd for x in ["what time", "tell me the time", "tell me current time",
                               "whats the time", "what's the time", "current time",
                               "what time is it", "time is it"])
        and not _word(cmd, "alarm", "timer")
    ):
        now = datetime.now()
        response = f"It's {now.strftime(Config.TIME_FORMAT)}."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if any(w in cmd for w in ["set alarm", "set an alarm", "alarm for", "alarm at", "wake me"]):
        phrase = extract_time_phrase(original)
        try:
            ok = parse_time(original, datetime.now()) is not None
        except TimeParseError as e:
            ok = False
            response = f"That isn't a valid time: {e}"
        else:
            response = ""
        if ok:
            response = orch.alarm.set_alarm(phrase, _alarm_label(original))
        elif not response:
            response = "Say 'set alarm for 7:30 AM'."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if any(w in cmd for w in ["set timer", "set a timer", "timer for", "countdown", "count down"]):
        seconds = _parse_duration(original)
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

    if any(w in cmd for w in ["cancel all alarms", "cancel all timers", "cancel all"]):
        if "alarm" in cmd:
            response = orch.alarm.cancel_all_alarms()
        elif "timer" in cmd:
            response = orch.alarm.cancel_all_timers()
        else:
            response = orch.alarm.cancel_all_alarms() + " " + orch.alarm.cancel_all_timers()
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if _word(cmd, "cancel", "stop", "clear", "end", "kill") and _word(cmd, "timer", "alarm", "countdown"):
        if _word(cmd, "alarm"):
            response = orch.alarm.cancel_last_alarm()
        else:
            response = orch.alarm.cancel_last_timer()
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    response = "Say 'set alarm for 7 AM' or 'timer for 10 minutes'."
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

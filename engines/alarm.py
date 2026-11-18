import itertools
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from utils.config import Config
from utils.voice_parse import TimeParseError, format_duration, parse_time, seconds_until

_MAX_TRIGGERED = 100  # bound on remembered fired alarms/timers


class AlarmEngine:
    """Local alarm and timer system using threading with voice alerts."""

    def __init__(self, speak_callback: Callable | None = None):
        self._alarms: dict[str, threading.Timer] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._active_countdowns: list[dict] = []
        self._lock = threading.RLock()
        self._alarm_ids = itertools.count(1)   # monotonic: ids never reused after cancel
        self._timer_ids = itertools.count(1)
        self._speak = speak_callback or self._default_speak
        self._now: Callable[[], datetime] = datetime.now  # patched in tests

    def _default_speak(self, text: str):
        """Default speak function if no callback provided."""
        try:
            import winsound
            for _ in range(3):
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                time.sleep(0.3)
        except Exception as _e:
            logging.debug("[engines/alarm.py:24] Swallowed exception: %s: %s", type(_e).__name__, _e)
            print(f"[ALERT] {text}")

    def set_speak_callback(self, callback: Callable):
        """Set the speak callback (called by orchestrator)."""
        self._speak = callback

    def _record(self, entry: dict):
        with self._lock:
            self._active_countdowns.append(entry)
            overflow = len(self._active_countdowns) - _MAX_TRIGGERED
            if overflow > 0:
                del self._active_countdowns[:overflow]

    def set_alarm(self, time_str: str, label: str = "Alarm") -> str:
        """Set alarm for a specific time ('7:30 AM', '7 am', '5pm', 'noon', '14:00')."""
        try:
            now = self._now()
            text = (time_str or "").strip()
            target = parse_time(text, now)
            if target is None and text:
                target = parse_time("at " + text, now)
            if target is None:
                return f"Could not understand time format: {time_str}"
            delay = max(seconds_until(target, now), 0.0)
            shown = target.strftime(Config.TIME_FORMAT)
            with self._lock:
                alarm_id = f"alarm_{next(self._alarm_ids)}"

            def _ring():
                with self._lock:
                    self._alarms.pop(alarm_id, None)
                self._record({
                    "type": "alarm",
                    "label": label,
                    "time": shown,
                    "triggered": True,
                    "triggered_at": datetime.now().isoformat(),
                })
                self._speak(f"Alarm! {label}! It's {shown}.")

            timer = threading.Timer(delay, _ring)
            timer.daemon = True
            with self._lock:
                self._alarms[alarm_id] = timer
            timer.start()
            return f"Alarm set for {shown} ({label})."
        except TimeParseError as e:
            return f"That isn't a valid time: {e}"
        except Exception as e:
            logging.debug("[engines/alarm.py:66] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"Could not set alarm: {e}"

    def set_timer(self, seconds: float, label: str = "Timer") -> str:
        """Set a countdown timer that speaks when done."""
        if not seconds or seconds <= 0:
            return "Timer duration must be positive."
        seconds = float(seconds)
        with self._lock:
            timer_id = f"timer_{next(self._timer_ids)}"
        end_time = self._now() + timedelta(seconds=seconds)
        time_str = format_duration(seconds)

        def _ring():
            with self._lock:
                self._timers.pop(timer_id, None)
            self._record({
                "type": "timer",
                "label": label,
                "duration": time_str,
                "ended_at": end_time.strftime("%H:%M:%S"),
                "triggered": True,
                "triggered_at": datetime.now().isoformat(),
            })
            self._speak(f"Timer finished! {label} of {time_str} is complete.")

        timer = threading.Timer(seconds, _ring)
        timer.daemon = True
        with self._lock:
            self._timers[timer_id] = timer
        timer.start()
        return f"Timer set for {time_str} ({label})."

    def cancel_alarm(self, alarm_id: str) -> str:
        with self._lock:
            timer = self._alarms.pop(alarm_id, None)
            if timer:
                timer.cancel()
                return f"Alarm {alarm_id} cancelled."
            return f"Alarm {alarm_id} not found."

    def cancel_timer(self, timer_id: str) -> str:
        with self._lock:
            timer = self._timers.pop(timer_id, None)
            if timer:
                timer.cancel()
                return f"Timer {timer_id} cancelled."
            return f"Timer {timer_id} not found."

    def cancel_all_alarms(self) -> str:
        with self._lock:
            n = len(self._alarms)
            for t in self._alarms.values():
                t.cancel()
            self._alarms.clear()
            return f"Cancelled {n} alarm(s)." if n else "No alarms to cancel."

    def cancel_all_timers(self) -> str:
        with self._lock:
            n = len(self._timers)
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
            return f"Cancelled {n} timer(s)." if n else "No timers to cancel."

    def cancel_last_timer(self) -> str:
        with self._lock:
            if not self._timers:
                return "No active timers."
            last_id = list(self._timers.keys())[-1]
            t = self._timers.pop(last_id)
            t.cancel()
            return f"Cancelled {last_id}."

    def cancel_last_alarm(self) -> str:
        with self._lock:
            if not self._alarms:
                return "No active alarms."
            last_id = list(self._alarms.keys())[-1]
            t = self._alarms.pop(last_id)
            t.cancel()
            return f"Cancelled {last_id}."

    def list_alarms(self) -> str:
        with self._lock:
            n = len(self._alarms)
        return f"{n} alarm(s) active." if n else "No active alarms."

    def list_timers(self) -> str:
        with self._lock:
            n = len(self._timers)
        return f"{n} timer(s) active." if n else "No active timers."

    def get_triggered(self) -> list[dict]:
        """Get list of triggered alarms/timers."""
        with self._lock:
            triggered = [d for d in self._active_countdowns if d.get("triggered")]
            self._active_countdowns = [d for d in self._active_countdowns if not d.get("triggered")]
        return triggered

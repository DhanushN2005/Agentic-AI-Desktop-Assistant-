import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable


class AlarmEngine:
    """Local alarm and timer system using threading with voice alerts."""

    def __init__(self, speak_callback: Optional[Callable] = None):
        self._alarms: Dict[str, threading.Timer] = {}
        self._timers: Dict[str, threading.Timer] = {}
        self._active_countdowns: List[dict] = []
        self._lock = threading.Lock()
        self._speak = speak_callback or self._default_speak

    def _default_speak(self, text: str):
        """Default speak function if no callback provided."""
        try:
            import winsound
            for _ in range(3):
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                time.sleep(0.3)
        except Exception:
            print(f"[ALERT] {text}")

    def set_speak_callback(self, callback: Callable):
        """Set the speak callback (called by orchestrator)."""
        self._speak = callback

    def set_alarm(self, time_str: str, label: str = "Alarm") -> str:
        """Set alarm for a specific time (e.g., '7:30 AM', '14:00')."""
        try:
            now = datetime.now()
            target = None
            for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M", "%I:%M"]:
                try:
                    target = datetime.strptime(time_str.strip(), fmt).replace(
                        year=now.year, month=now.month, day=now.day
                    )
                    break
                except ValueError:
                    continue
            if target is None:
                return f"Could not understand time format: {time_str}"
            if target <= now:
                target += timedelta(days=1)
            delay = (target - now).total_seconds()
            alarm_id = f"alarm_{len(self._alarms) + 1}"

            def _ring():
                self._speak(f"Alarm! {label}! It's {time_str}.")
                self._active_countdowns.append({
                    "type": "alarm",
                    "label": label,
                    "time": time_str,
                    "triggered": True,
                    "triggered_at": datetime.now().isoformat()
                })

            timer = threading.Timer(delay, _ring)
            timer.daemon = True
            timer.start()
            self._alarms[alarm_id] = timer
            return f"Alarm set for {time_str} ({label})."
        except Exception as e:
            return f"Could not set alarm: {e}"

    def set_timer(self, seconds: int, label: str = "Timer") -> str:
        """Set a countdown timer that speaks when done."""
        if seconds <= 0:
            return "Timer duration must be positive."
        timer_id = f"timer_{len(self._timers) + 1}"
        end_time = datetime.now() + timedelta(seconds=seconds)

        def _ring():
            mins, secs = divmod(seconds, 60)
            time_str = f"{mins} minutes {secs} seconds" if mins else f"{secs} seconds"
            self._speak(f"Timer finished! {label} of {time_str} is complete.")
            self._active_countdowns.append({
                "type": "timer",
                "label": label,
                "duration": time_str,
                "ended_at": end_time.strftime("%H:%M:%S"),
                "triggered": True,
                "triggered_at": datetime.now().isoformat()
            })

        timer = threading.Timer(seconds, _ring)
        timer.daemon = True
        timer.start()
        self._timers[timer_id] = timer
        mins, secs = divmod(seconds, 60)
        time_str = f"{mins} minutes {secs} seconds" if mins else f"{secs} seconds"
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

    def list_alarms(self) -> str:
        if not self._alarms:
            return "No active alarms."
        return f"{len(self._alarms)} alarm(s) active."

    def list_timers(self) -> str:
        if not self._timers:
            return "No active timers."
        return f"{len(self._timers)} timer(s) active."

    def get_triggered(self) -> List[dict]:
        """Get list of triggered alarms/timers."""
        triggered = [d for d in self._active_countdowns if d.get("triggered")]
        self._active_countdowns = [d for d in self._active_countdowns if not d.get("triggered")]
        return triggered

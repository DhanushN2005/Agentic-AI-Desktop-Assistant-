import threading
import time
from datetime import datetime


class PomodoroEngine:
    """Pomodoro focus timer engine."""

    def __init__(self):
        self.work_duration = 25 * 60  # 25 minutes default
        self.break_duration = 5 * 60  # 5 minutes default
        self.long_break_duration = 15 * 60  # 15 minutes
        self.sessions_before_long = 4
        self._timer = None
        self._running = False
        self._sessions_completed = 0
        self._callback = None

    def set_callback(self, callback):
        self._callback = callback

    def start(self, work_minutes: int = None, break_minutes: int = None):
        if work_minutes:
            self.work_duration = work_minutes * 60
        if break_minutes:
            self.break_duration = break_minutes * 60

        self._running = True
        self._sessions_completed = 0
        self._run_session(is_work=True)

    def _run_session(self, is_work: bool):
        if not self._running:
            return

        duration = self.work_duration if is_work else self.break_duration
        if not is_work and self._sessions_completed > 0 and self._sessions_completed % self.sessions_before_long == 0:
            duration = self.long_break_duration

        session_type = "Work" if is_work else ("Long Break" if duration == self.long_break_duration else "Break")

        if self._callback:
            self._callback(f"Pomodoro {session_type} started — {duration // 60} minutes")

        def _countdown():
            remaining = duration
            while remaining > 0 and self._running:
                time.sleep(1)
                remaining -= 1
            if self._running:
                if is_work:
                    self._sessions_completed += 1
                    if self._callback:
                        self._callback(f"Work session complete! Session {self._sessions_completed}. Time for a break.")
                else:
                    if self._callback:
                        self._callback("Break over! Ready to work?")
                # Auto-start next session
                self._run_session(is_work=not is_work)

        self._timer = threading.Thread(target=_countdown, daemon=True)
        self._timer.start()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.join(timeout=2)

    def status(self) -> str:
        if self._running:
            return f"Pomodoro running. Sessions completed: {self._sessions_completed}."
        return "No pomodoro session active."

    def get_sessions(self) -> int:
        return self._sessions_completed

import threading


class PomodoroEngine:
    """Pomodoro focus timer engine (one loop thread, Event-based waits)."""

    def __init__(self):
        self.work_duration = 25 * 60  # 25 minutes default
        self.break_duration = 5 * 60  # 5 minutes default
        self.long_break_duration = 15 * 60  # 15 minutes
        self.sessions_before_long = 4
        self._timer = None
        self._running = False
        self._sessions_completed = 0
        self._callback = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def set_callback(self, callback):
        self._callback = callback

    def _say(self, msg: str):
        cb = self._callback
        if cb:
            try:
                cb(msg)
            except Exception:  # a broken callback must never kill the loop
                pass

    def start(self, work_minutes: int = None, break_minutes: int = None) -> bool:
        """Start the loop. Returns False (and starts nothing) if already running."""
        with self._lock:
            if self._running and self._timer is not None and self._timer.is_alive():
                return False
            if work_minutes:
                self.work_duration = work_minutes * 60
            if break_minutes:
                self.break_duration = break_minutes * 60
            self._running = True
            self._sessions_completed = 0
            self._stop_event = threading.Event()
            stop = self._stop_event
            self._timer = threading.Thread(target=self._loop, args=(stop,), daemon=True)
            self._timer.start()
            return True

    def _session_duration(self, is_work: bool) -> float:
        if is_work:
            return self.work_duration
        if self._sessions_completed > 0 and self._sessions_completed % self.sessions_before_long == 0:
            return self.long_break_duration
        return self.break_duration

    def _loop(self, stop: threading.Event):
        is_work = True
        while not stop.is_set():
            duration = self._session_duration(is_work)
            if is_work:
                session_type = "Work"
            else:
                session_type = "Long Break" if duration == self.long_break_duration else "Break"
            self._say(f"Pomodoro {session_type} started — {duration // 60:g} minutes")
            if stop.wait(duration):  # returns True if stopped early
                break
            if is_work:
                self._sessions_completed += 1
                self._say(f"Work session complete! Session {self._sessions_completed}. Time for a break.")
            else:
                self._say("Break over! Ready to work?")
            is_work = not is_work
        with self._lock:
            if self._stop_event is stop:
                self._running = False

    def stop(self):
        with self._lock:
            self._running = False
            self._stop_event.set()
            t = self._timer
        if t and t is not threading.current_thread():
            t.join(timeout=2)

    def status(self) -> str:
        if self._running:
            return f"Pomodoro running. Sessions completed: {self._sessions_completed}."
        return "No pomodoro session active."

    def get_sessions(self) -> int:
        return self._sessions_completed

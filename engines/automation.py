"""Automation Scheduler - cron-like jobs for Flexie."""
import time
import threading
import logging
from typing import Dict, List, Callable
from datetime import datetime

# ---- Compatibility shims for orchestrator (fixes ImportError: cannot import name 'GoalExecutor') ----
# Original repo exported GoalExecutor/RuleEngine; current file only has AutomationScheduler.
# Provide lightweight stubs so core/orchestrator.py:52 import succeeds and _monitor_loop keeps working.

class GoalExecutor:
    """Stub — orchestrator instantiates but never calls complex methods directly."""
    def __init__(self, orch):
        self.orch = orch
        self.logger = logging.getLogger("Flexie.GoalExecutor")
    def execute(self, goal: str, *args, **kwargs):
        self.logger.info(f"GoalExecutor stub: {goal}")
        try:
            self.orch.cmd_queue.put(goal)
        except: pass
        return f"Queued goal: {goal}"

class RuleEngine:
    """Stub — provides monitor_and_trigger() used in orchestrator _monitor_loop:924."""
    def __init__(self, orch):
        self.orch = orch
        self.logger = logging.getLogger("Flexie.RuleEngine")
    def monitor_and_trigger(self):
        # No-op: real scheduling is done by AutomationScheduler. Kept for compatibility.
        pass
    def add_rule(self, *a, **kw): pass
    def remove_rule(self, *a, **kw): pass

class AutomationScheduler:
    """Simple in-process scheduler for recurring tasks."""
    def __init__(self, orchestrator):
        self.orch = orchestrator
        self.jobs: Dict[str, dict] = {}
        self._running = False
        self._thread = None
        self.logger = logging.getLogger("Flexie.Automation")

    def add_job(self, job_id: str, command: str, trigger: str = "daily", hour: int = 9, minute: int = 0, interval: int = 3600):
        """Add a scheduled job.
        trigger: daily, interval, once
        """
        self.jobs[job_id] = {
            "command": command,
            "trigger": trigger,
            "hour": hour,
            "minute": minute,
            "interval": interval,
            "last_run": 0,
        }
        self.logger.info(f"Automation: Added job {job_id} -> {command} [{trigger}]")
        return True

    def remove_job(self, job_id: str) -> bool:
        if job_id in self.jobs:
            del self.jobs[job_id]
            return True
        return False

    def list_jobs(self) -> List[str]:
        if not self.jobs:
            return ["No scheduled automations."]
        return [f"{jid}: {j['command']} [{j['trigger']}]" for jid, j in self.jobs.items()]

    def start(self):
        if self._running:
            return
        # Add built-in automations if none exist
        if not self.jobs:
            self.add_job("daily_briefing", "daily briefing", trigger="daily", hour=9, minute=0)
            self.add_job("auto_organize", "organize desktop", trigger="daily", hour=18, minute=0)
            self.logger.info("Automation: Added built-in daily jobs")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.logger.info("Automation scheduler started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                now = datetime.now()
                for job_id, job in list(self.jobs.items()):
                    should_run = False
                    if job["trigger"] == "daily":
                        # Run once per day at hour:minute
                        if now.hour == job["hour"] and now.minute == job["minute"]:
                            if time.time() - job["last_run"] > 3600:
                                should_run = True
                    elif job["trigger"] == "interval":
                        if time.time() - job["last_run"] > job["interval"]:
                            should_run = True
                    elif job["trigger"] == "hourly":
                        if time.time() - job["last_run"] > 3600:
                            should_run = True

                    if should_run:
                        self.logger.info(f"Automation: Triggering {job_id} -> {job['command']}")
                        job["last_run"] = time.time()
                        try:
                            self.orch.cmd_queue.put(job["command"])
                        except Exception as e:
                            self.logger.error(f"Automation trigger failed: {e}")
            except Exception as e:
                self.logger.error(f"Automation loop error: {e}")
            time.sleep(60)  # check every minute

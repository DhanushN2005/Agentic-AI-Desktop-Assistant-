"""Automation Scheduler - cron-like jobs for Flexie."""
import logging
import threading
import time
from datetime import datetime, timedelta

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
        except Exception as _e:
            logging.debug("[engines/automation.py:21] Swallowed exception: %s: %s", type(_e).__name__, _e)
        return f"Queued goal: {goal}"

class RuleEngine:
    """Condition -> command rules evaluated in orchestrator _monitor_loop.

    Rule shape: {"condition": str|dict|callable, "command": str,
                 "cooldown": seconds, "enabled": bool}
    String conditions: "cpu_high", "ram_high", "batt_low",
      "cpu>85", "ram>90", "batt<20", "always".
    Dict conditions: {"metric": "cpu"|"ram"|"batt", "gt": x} or {"lt": x}.
    """
    def __init__(self, orch):
        self.orch = orch
        self.logger = logging.getLogger("Flexie.RuleEngine")
        self.rules: dict[str, dict] = {}
        self._last_fired: dict[str, float] = {}

    def add_rule(self, rule_id: str = None, condition=None, command: str = None,
                 cooldown: int = 300, enabled: bool = True, **kw) -> bool:
        # Back-compat: add_rule(*a, **kw) no-op -> now real. Accept positional
        # add_rule("id", "cpu_high", "system report") and kw forms.
        if rule_id is None:
            rule_id = kw.get("rule_id") or kw.get("name") or f"rule_{len(self.rules)}"
        if condition is None:
            condition = kw.get("condition", "always")
        if command is None:
            command = kw.get("command", "")
        if not command:
            return False
        self.rules[str(rule_id)] = {
            "condition": condition, "command": command,
            "cooldown": cooldown, "enabled": enabled,
        }
        self.logger.info(f"RuleEngine: added rule {rule_id} -> {command} [{condition}]")
        return True

    def remove_rule(self, rule_id: str = None, *a, **kw) -> bool:
        rid = str(rule_id if rule_id is not None else kw.get("rule_id", ""))
        if rid in self.rules:
            del self.rules[rid]
            self._last_fired.pop(rid, None)
            return True
        return False

    def list_rules(self) -> list[str]:
        if not self.rules:
            return ["No automation rules."]
        return [f"{rid}: {r['command']} when [{r['condition']}]"
                f"{'' if r.get('enabled', True) else ' (disabled)'}"
                for rid, r in self.rules.items()]

    def _metrics_snapshot(self):
        try:
            from engines.system import SystemCtrl
            cpu_val, ram_val = SystemCtrl.cpu_ram()
            try:
                batt = SystemCtrl.battery_status()
            except Exception:
                batt = 100
            return float(cpu_val or 0), float(ram_val or 0), batt
        except Exception:
            return 0.0, 0.0, 100

    def _evaluate(self, condition, cpu: float, ram: float, batt) -> bool:
        try:
            batt_val = float(batt) if isinstance(batt, (int, float)) else 100.0
        except Exception:
            batt_val = 100.0
        if callable(condition):
            try:
                return bool(condition({"cpu": cpu, "ram": ram, "batt": batt_val}))
            except Exception:
                return False
        if isinstance(condition, dict):
            metric = str(condition.get("metric", "")).lower()
            val = {"cpu": cpu, "ram": ram, "batt": batt_val,
                   "battery": batt_val}.get(metric, None)
            if val is None:
                return False
            if "gt" in condition:
                return val > float(condition["gt"])
            if "lt" in condition:
                return val < float(condition["lt"])
            if "ge" in condition:
                return val >= float(condition["ge"])
            if "le" in condition:
                return val <= float(condition["le"])
            return False
        text = str(condition or "").strip().lower()
        if not text or text == "always":
            return True
        if text in ("cpu_high", "high cpu"):
            return cpu >= 85.0
        if text in ("ram_high", "high ram", "high memory"):
            return ram >= 90.0
        if text in ("batt_low", "battery_low", "low battery"):
            return batt_val <= 20.0
        import re as _re
        m = _re.match(r"^(cpu|ram|batt|battery)\s*(>=|<=|>|<|==)\s*(\d+(?:\.\d+)?)$", text)
        if m:
            metric, op, num = m.group(1), m.group(2), float(m.group(3))
            val = {"cpu": cpu, "ram": ram, "batt": batt_val, "battery": batt_val}[metric]
            return {" >": val > num, ">": val > num, "<": val < num,
                    ">=": val >= num, "<=": val <= num, "==": val == num}[op]
        return False

    def monitor_and_trigger(self):
        if not self.rules:
            return
        cpu, ram, batt = self._metrics_snapshot()
        now = time.time()
        for rid, rule in list(self.rules.items()):
            try:
                if not rule.get("enabled", True):
                    continue
                if now - self._last_fired.get(rid, 0) < rule.get("cooldown", 300):
                    continue
                if self._evaluate(rule.get("condition"), cpu, ram, batt):
                    self._last_fired[rid] = now
                    cmd = rule.get("command", "")
                    self.logger.info(f"RuleEngine: firing {rid} -> {cmd}")
                    try:
                        self.orch.cmd_queue.put(cmd)
                    except Exception as _e:
                        logging.debug("[engines/automation.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            except Exception as e:
                self.logger.error(f"RuleEngine rule {rid} error: {e}")

class AutomationScheduler:
    """In-process scheduler: stored ``next_run`` per job, persisted, sleeps until the next due time."""

    CATCH_UP_GRACE = 6 * 3600     # fire a missed daily/once job once if within this window
    MAX_SLEEP = 3600.0

    def __init__(self, orchestrator, *, clock=None, store_path: str | None = None, autoload: bool = True):
        self.orch = orchestrator
        self.jobs: dict[str, dict] = {}
        self._running = False
        self._thread = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._clock = clock or time.time
        self._store_path = store_path
        self._defaults_seeded = False
        self.logger = logging.getLogger("Flexie.Automation")
        if autoload:
            self._load()

    # ------------------------------------------------------------------ persistence
    def _path(self) -> str:
        if self._store_path:
            return self._store_path
        from utils.paths import data_file
        return data_file("automation_jobs.json")

    def _save(self) -> None:
        import json
        import os
        try:
            # Serialise AND write under the lock: concurrent savers must not interleave on the
            # shared temp file or dump a dict another thread is mutating.
            with self._lock:
                payload = {"jobs": self.jobs, "defaults_seeded": self._defaults_seeded}
                tmp = self._path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                os.replace(tmp, self._path())
        except Exception as e:
            self.logger.debug("automation save failed: %s", e)

    def _load(self) -> None:
        import json
        import os
        if not os.path.exists(self._path()):
            return
        try:
            with open(self._path(), encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.logger.debug("automation load failed: %s", e)
            return
        now = self._clock()
        with self._lock:
            self._defaults_seeded = bool(data.get("defaults_seeded", False))
            for jid, job in (data.get("jobs") or {}).items():
                job.setdefault("enabled", True)
                job.setdefault("last_run", 0)
                nxt = job.get("next_run")
                if nxt is None:
                    job["next_run"] = self._next_after(job, now)
                elif nxt <= now:
                    missed_by = now - nxt
                    keep = job.get("trigger") in ("daily", "once") and missed_by <= self.CATCH_UP_GRACE
                    if job.get("trigger") == "once" and not keep:
                        continue                      # expired one-shot
                    if not keep:
                        job["next_run"] = self._next_after(job, now)
                self.jobs[jid] = job

    # ------------------------------------------------------------------ time math
    def _next_after(self, job: dict, after: float):
        trig = job.get("trigger", "daily")
        if trig == "daily":
            base = datetime.fromtimestamp(after).replace(
                hour=int(job.get("hour", 9)), minute=int(job.get("minute", 0)), second=0, microsecond=0)
            if base.timestamp() <= after:
                base += timedelta(days=1)
            return base.timestamp()
        if trig == "hourly":
            return after + 3600
        if trig == "interval":
            return after + max(1, int(job.get("interval", 3600)))
        if trig == "once":
            return job.get("run_at")
        return None

    # ------------------------------------------------------------------ job api
    def add_job(self, job_id: str, command: str, trigger: str = "daily", hour: int = 9, minute: int = 0,
                interval: int = 3600, run_at: float | None = None, enabled: bool = True):
        """Add a scheduled job. trigger: daily, hourly, interval, once (needs run_at epoch seconds)."""
        if trigger not in ("daily", "hourly", "interval", "once"):
            raise ValueError(f"Unknown trigger: {trigger}")
        if trigger == "once" and run_at is None:
            raise ValueError("A 'once' job needs run_at")
        job = {
            "command": command, "trigger": trigger, "hour": hour, "minute": minute,
            "interval": interval, "run_at": run_at, "last_run": 0, "enabled": enabled,
        }
        job["next_run"] = self._next_after(job, self._clock())
        with self._lock:
            self.jobs[job_id] = job
        self._save()
        self._wake.set()
        self.logger.info(f"Automation: Added job {job_id} -> {command} [{trigger}]")
        return True

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            existed = self.jobs.pop(job_id, None) is not None
        if existed:
            self._save()
            self._wake.set()
        return existed

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job["enabled"] = enabled
            if enabled:
                job["next_run"] = self._next_after(job, self._clock())
        self._save()
        self._wake.set()
        return True

    def list_jobs(self) -> list[str]:
        with self._lock:
            if not self.jobs:
                return ["No scheduled automations."]
            out = []
            for jid, j in self.jobs.items():
                nxt = j.get("next_run")
                when = datetime.fromtimestamp(nxt).strftime("%a %H:%M") if nxt else "never"
                state = "" if j.get("enabled", True) else " (disabled)"
                out.append(f"{jid}: {j['command']} [{j['trigger']}] next {when}{state}")
            return out

    # ------------------------------------------------------------------ run loop
    def start(self):
        if self._running:
            return
        with self._lock:
            seed = not self.jobs and not self._defaults_seeded
        if seed:
            self.add_job("daily_briefing", "daily briefing", trigger="daily", hour=9, minute=0)
            # Unattended file moves are OFF by default (EN-21); enable explicitly.
            self.add_job("auto_organize", "organize desktop", trigger="daily", hour=18, minute=0, enabled=False)
            self._defaults_seeded = True
            self._save()
            self.logger.info("Automation: Added built-in jobs (auto_organize disabled by default)")
        self._running = True
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="automation")
        self._thread.start()
        self.logger.info("Automation scheduler started")

    def stop(self):
        self._running = False
        self._wake.set()

    def run_due(self, now: float | None = None) -> list[tuple[str, str]]:
        """Fire every enabled job whose next_run <= now, then advance it.

        Returns ``[(job_id, command), ...]`` for the jobs that fired.
        """
        now = self._clock() if now is None else now
        fired: list[tuple[str, str]] = []
        with self._lock:
            for job_id, job in list(self.jobs.items()):
                nxt = job.get("next_run")
                if not job.get("enabled", True) or nxt is None or nxt > now:
                    continue
                fired.append((job_id, job["command"]))
                job["last_run"] = now
                if job["trigger"] == "once":
                    del self.jobs[job_id]
                else:
                    job["next_run"] = self._next_after(job, now)   # one catch-up, then advance past now
        return fired

    def _seconds_until_next(self, now: float) -> float:
        with self._lock:
            times = [j["next_run"] for j in self.jobs.values()
                     if j.get("enabled", True) and j.get("next_run") is not None]
        if not times:
            return self.MAX_SLEEP
        return min(self.MAX_SLEEP, max(0.0, min(times) - now))

    def _loop(self):
        while self._running:
            try:
                self._tick()
            except Exception as e:
                self.logger.error(f"Automation loop error: {e}")
            delay = self._seconds_until_next(self._clock())
            self._wake.wait(timeout=max(0.2, delay))
            self._wake.clear()

    def _tick(self) -> list[tuple[str, str]]:
        fired = self.run_due(self._clock())
        for job_id, cmd in fired:
            self.logger.info(f"Automation: Triggering {job_id} -> {cmd}")
            try:
                self.orch.cmd_queue.put(cmd)
            except Exception as e:
                self.logger.error(f"Automation trigger failed: {e}")
        if fired:
            self._save()
        return fired

"""Automation Scheduler - cron-like jobs for Flexie."""
import time
import threading
import logging
from typing import Dict, List
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
        self.rules: Dict[str, dict] = {}
        self._last_fired: Dict[str, float] = {}

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

    def list_rules(self) -> List[str]:
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

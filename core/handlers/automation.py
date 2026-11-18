import re


def handle_automation(orch, c):
    cmd = c.lower().strip()
    if any(x in cmd for x in ["list", "show"]):
        jobs = orch.automation.list_jobs() if orch.automation else ["Automation not available"]
        orch.speak("\n".join(jobs))
        return True
    m_toggle = re.match(r"^(enable|disable|turn on|turn off)\s+(?:automation\s+)?(\w+)", cmd)
    if m_toggle and orch.automation:
        jid = m_toggle.group(2)
        on = m_toggle.group(1) in ("enable", "turn on")
        if orch.automation.set_enabled(jid, on):
            orch.speak(f"Automation {jid} is now {'enabled' if on else 'disabled'}.")
        else:
            orch.speak("I don't have an automation with that name. Say list automations first.")
        return True
    m_once = re.search(r"(?:schedule\s+)?(.+?)\s+in\s+(\d+)\s+(minute|hour)s?\b", cmd)
    if m_once and orch.automation:
        import time as _time
        delay = int(m_once.group(2)) * (3600 if m_once.group(3) == "hour" else 60)
        task_cmd = re.sub(r"^(schedule|automate)\s+", "", m_once.group(1)).strip()
        jid = re.sub(r"\W+", "_", task_cmd)[:20] or "once_job"
        orch.automation.add_job(jid, task_cmd, trigger="once", run_at=_time.time() + delay)
        orch.speak(f"Okay, I will run {task_cmd} once in {m_once.group(2)} {m_once.group(3)}s.")
        return True
    if any(x in cmd for x in ["remove", "delete", "cancel"]):
        m = re.search(r"(?:automation\s+)?(\w+)", cmd)
        jid = m.group(1) if m else ""
        # try to find job id
        if orch.automation and orch.automation.remove_job(jid):
            orch.speak(f"Removed automation {jid}")
        else:
            orch.speak("Which automation to remove? Say list automations first.")
        return True
    # schedule: "schedule X daily at 9am" or "every hour do Y"
    # Extract command after "daily at" or "every hour" or "schedule"
    m = re.search(r"(?:schedule\s+)?(.+?)\s+(?:daily at|every day at|every hour|daily)\s*(\d+)?", cmd)
    if m:
        task_cmd = m.group(1).replace("schedule", "").strip()
        # Fallback: everything after schedule
        if not task_cmd:
            task_cmd = re.sub(r"^(schedule|automate)\s+", "", cmd).strip()
        jid = re.sub(r'\W+', '_', task_cmd)[:20] or f"job_{len(orch.automation.jobs)+1}"
        hour = int(m.group(2)) if m.group(2) and m.group(2).isdigit() else 9
        trigger = "hourly" if "hour" in cmd else "daily"
        orch.automation.add_job(jid, task_cmd, trigger=trigger, hour=hour)
        orch.speak(f"Scheduled {task_cmd} {trigger} at {hour}")
        return True
    # Generic schedule
    task = re.sub(r"^(schedule|automate)\s+", "", c).strip()
    if task:
        jid = re.sub(r'\W+', '_', task)[:20] or "job1"
        orch.automation.add_job(jid, task, trigger="daily", hour=9)
        orch.speak(f"Scheduled {task} daily at 9am")
    else:
        orch.speak("What should I schedule? Say schedule check gmail daily at 9am")
    return True

import re

def handle_automation(orch, c):
    cmd = c.lower().strip()
    if any(x in cmd for x in ["list", "show"]):
        jobs = orch.automation.list_jobs() if orch.automation else ["Automation not available"]
        orch.speak("\n".join(jobs))
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

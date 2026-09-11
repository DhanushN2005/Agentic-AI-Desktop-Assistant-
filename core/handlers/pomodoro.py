import re


def handle_pomodoro(orch, c):
    """Handle pomodoro timer commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "stop" in cmd or "cancel" in cmd or "end" in cmd or "pause" in cmd:
        orch.pomodoro.stop()
        response = "Pomodoro stopped."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if "status" in cmd or "check" in cmd or "sessions" in cmd:
        response = orch.pomodoro.status()
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if "start" in cmd or "begin" in cmd or "start focus" in cmd or "pomodoro" in cmd:
        work_match = re.search(r"(\d+)\s*(?:min|work)", cmd)
        break_match = re.search(r"break\s*(?:of\s+)?(\d+)", cmd)
        work_mins = int(work_match.group(1)) if work_match else None
        break_mins = int(break_match.group(1)) if break_match else None

        def cb(msg):
            orch.speak(msg)

        orch.pomodoro.set_callback(cb)
        orch.pomodoro.start(work_minutes=work_mins, break_minutes=break_mins)
        response = f"Pomodoro started! {orch.pomodoro.work_duration // 60} min work, {orch.pomodoro.break_duration // 60} min break."
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    response = "Say 'start pomodoro', 'pomodoro status', or 'stop pomodoro'."
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

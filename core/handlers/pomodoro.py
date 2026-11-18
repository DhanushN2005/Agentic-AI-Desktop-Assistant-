import re


def _has(cmd: str, *words: str) -> bool:
    """Whole-word match so 'weekend' / 'send' never trigger 'end'."""
    return any(re.search(rf"\b{re.escape(w)}\b", cmd) for w in words)


def _reply(orch, c, response):
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True


def handle_pomodoro(orch, c):
    """Handle pomodoro timer commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if _has(cmd, "stop", "cancel", "end", "pause"):
        orch.pomodoro.stop()
        return _reply(orch, c, "Pomodoro stopped.")

    if _has(cmd, "status", "check", "sessions"):
        return _reply(orch, c, orch.pomodoro.status())

    if _has(cmd, "start", "begin", "pomodoro"):
        work_match = re.search(r"(\d+)\s*(?:min|work)", cmd)
        break_match = re.search(r"break\s*(?:of\s+)?(\d+)", cmd)
        work_mins = int(work_match.group(1)) if work_match else None
        break_mins = int(break_match.group(1)) if break_match else None

        def cb(msg):
            orch.speak(msg)

        orch.pomodoro.set_callback(cb)
        started = orch.pomodoro.start(work_minutes=work_mins, break_minutes=break_mins)
        if started is False:
            return _reply(orch, c, "A pomodoro is already running. Say 'stop pomodoro' first.")
        response = (f"Pomodoro started! {orch.pomodoro.work_duration // 60} min work, "
                    f"{orch.pomodoro.break_duration // 60} min break.")
        return _reply(orch, c, response)

    return _reply(orch, c, "Say 'start pomodoro', 'pomodoro status', or 'stop pomodoro'.")

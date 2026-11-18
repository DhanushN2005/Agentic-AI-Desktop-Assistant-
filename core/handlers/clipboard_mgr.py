import re

from utils.config import Config


def handle_clipboard_mgr(orch, c):
    """Handle clipboard manager commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if re.search(r"\b(?:start|enable|turn on)\b.*\bclipboard (?:history|monitor)", cmd):
        response = orch.clipboard_mgr.start_monitoring()
    elif re.search(r"\b(?:stop|disable|turn off)\b.*\bclipboard (?:history|monitor)", cmd):
        response = orch.clipboard_mgr.stop_monitoring()
    elif re.search(r"\bpin\b", cmd) and re.search(r"\d+", cmd):
        response = orch.clipboard_mgr.pin(int(re.search(r"\d+", cmd).group(0)))
    elif any(w in cmd for w in ["clipboard history", "show clipboard", "what did i copy", "clip history"]):
        response = orch.clipboard_mgr.history(Config.DEFAULT_CLIPBOARD_HISTORY)
    elif any(w in cmd for w in ["copy", "copy to clipboard"]):
        text_match = re.search(r"copy\s+(?:this\s+|to clipboard\s+)?(.+)", cmd)
        if text_match:
            response = orch.clipboard_mgr.copy(text_match.group(1).strip())
        else:
            response = "What would you like me to copy?"
    elif any(w in cmd for w in ["paste", "paste from clipboard"]):
        response = orch.clipboard_mgr.paste()
    elif "search clipboard" in cmd:
        query = re.search(r"search clipboard\s+(?:for\s+)?(.+)", cmd)
        if query:
            response = orch.clipboard_mgr.search(query.group(1).strip())
        else:
            response = "What should I search for in clipboard?"
    elif "clear clipboard" in cmd or "clear all clipboard" in cmd:
        wants_all = bool(re.search(r"\ball\b|\beverything\b|including pinned", cmd))
        response = orch.clipboard_mgr.clear(include_pinned=wants_all)
    else:
        response = orch.clipboard_mgr.history(Config.DEFAULT_CLIPBOARD_HISTORY)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

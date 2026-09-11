import re
from utils.config import Config


def handle_ip_lookup(orch, c):
    """Handle IP lookup commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if any(x in cmd for x in ["my ip", "public ip", "what is my ip", "whats my ip"]):
        response = orch.ip_lookup.get_public_ip()
    else:
        ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", cmd)
        if ip_match:
            response = orch.ip_lookup.lookup(ip_match.group(1))
        else:
            response = orch.ip_lookup.get_public_ip()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

import re

_IP_RE = re.compile(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])")
_DOMAIN_RE = re.compile(r"\b((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})\b", re.IGNORECASE)


def handle_ip_lookup(orch, c):
    """Handle IP lookup commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = re.sub(r"^\s*(?:hey\s+|ok\s+)?(?:flexie|flexi)\b[\s,]*", "", c.strip(), flags=re.IGNORECASE).strip()
    cmd = original.lower()

    if any(x in cmd for x in ["my ip", "public ip", "what is my ip", "whats my ip"]):
        response = orch.ip_lookup.get_public_ip()
    else:
        ip_match = _IP_RE.search(original)
        dom_match = None if ip_match else _DOMAIN_RE.search(original)
        if ip_match:
            response = orch.ip_lookup.lookup(ip_match.group(1))
        elif dom_match:
            response = orch.ip_lookup.lookup(dom_match.group(1))
        else:
            response = orch.ip_lookup.get_public_ip()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

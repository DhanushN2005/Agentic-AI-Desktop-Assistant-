import re


def handle_quotes(orch, c):
    """Handle quote commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Check for author
    author_match = re.search(r"(?:by|from|of)\s+(.+)", cmd)
    if author_match:
        response = orch.quotes.get_by_author(author_match.group(1).strip())
    # Check for tag/topic
    elif any(x in cmd for x in ["motivat", "inspir", "life", "love", "success", "wisdom", "humor"]):
        tag = "motivational"
        for t in ["inspirational", "life", "love", "success", "wisdom", "humor"]:
            if t in cmd:
                tag = t
                break
        response = orch.quotes.get_by_tag(tag)
    else:
        response = orch.quotes.get_random()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

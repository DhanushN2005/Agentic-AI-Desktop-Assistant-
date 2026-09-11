import re


def handle_jokes(orch, c):
    """Handle joke commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    category = None
    for cat in ["programming", "dark", "pun", "misc", "any"]:
        if cat in cmd:
            category = cat
            break

    if category and category != "any":
        response = orch.jokes.get_category(category)
    else:
        response = orch.jokes.get_joke()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

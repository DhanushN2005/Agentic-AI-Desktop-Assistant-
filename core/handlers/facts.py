import re


def handle_facts(orch, c):
    """Handle random fact commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Check for category
    category = None
    for cat in ["science", "history", "animal", "space", "technology", "food", "nature"]:
        if cat in cmd:
            category = cat
            break

    if category:
        response = orch.facts.get_by_category(category)
    else:
        response = orch.facts.get_random()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

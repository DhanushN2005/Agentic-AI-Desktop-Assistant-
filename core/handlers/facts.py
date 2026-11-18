import re

from utils.voice_parse import strip_wake


def handle_facts(orch, c):
    """Handle random fact commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = strip_wake(c).lower()

    # Check for category (whole words only: 'spacecraft' is not 'space')
    category = None
    for cat in ["science", "history", "animal", "space", "technology", "food", "nature"]:
        if re.search(rf"\b{cat}s?\b", cmd):
            category = cat
            break

    if category:
        response = orch.facts.get_by_category(category)
    else:
        response = orch.facts.get_random()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

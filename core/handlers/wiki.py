import re
from utils.config import Config


def handle_wiki(orch, c):
    """Handle Wikipedia search commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    query = re.sub(r"^(wiki|wikipedia|search wiki|look up|define|who is|what is|tell me about)\s*", "", cmd, flags=re.IGNORECASE).strip()
    if not query:
        orch.speak("What should I look up on Wikipedia?")
        return True

    response = orch.wiki.search(query)
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

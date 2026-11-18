import re

from utils.voice_parse import strip_wake

_PREFIX = re.compile(
    r"^(?:(?:search\s+)?(?:wikipedia|wiki)(?:\s+for)?|look\s*up|define|who\s+(?:is|was)|what\s+(?:is|are|was)|tell\s+me\s+about)\s*",
    re.IGNORECASE,
)


def handle_wiki(orch, c):
    """Handle Wikipedia search commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    # query keeps its original case (AC/DC, iPhone, NASA ...)
    query = original
    for _ in range(2):
        stripped = _PREFIX.sub("", query, count=1).strip()
        if stripped == query:
            break
        query = stripped
        if not query:
            break
    query = re.sub(r"^(?:on|for)\s+(?:wikipedia\s+)?", "", query, flags=re.IGNORECASE).strip()
    query = query.rstrip("?!. ").strip()
    if not query:
        orch.speak("What should I look up on Wikipedia?")
        return True

    response = orch.wiki.search(query)
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

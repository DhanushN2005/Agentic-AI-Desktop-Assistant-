import re

_AUTHOR_RE = re.compile(r"\b(?:quote|quotes|quotation)s?\s+(?:by|from)\s+(.+)$", re.IGNORECASE)
_AUTHOR_FALLBACK_RE = re.compile(r"\b(?:by|from)\s+(.+)$", re.IGNORECASE)
_NOT_AUTHORS = {"the day", "today", "the week", "the morning", "me", "my day"}


def handle_quotes(orch, c):
    """Handle quote commands (author names keep their original case)."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = re.sub(r"^\s*(?:hey\s+|ok\s+)?(?:flexie|flexi)\b[\s,]*", "", c.strip(), flags=re.IGNORECASE).strip()
    cmd = original.lower()

    author = None
    m = _AUTHOR_RE.search(original) or _AUTHOR_FALLBACK_RE.search(original)
    if m:
        cand = m.group(1).strip(" .?!")
        if cand.lower() not in _NOT_AUTHORS and cand:
            author = cand

    if author:
        response = orch.quotes.get_by_author(author)
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

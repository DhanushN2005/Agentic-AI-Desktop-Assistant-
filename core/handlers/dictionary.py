import re

from utils.voice_parse import strip_wake

_PATTERNS = [
    re.compile(r"\bwhat\s+does\s+(?P<w>.+?)\s+mean\b", re.IGNORECASE),
    re.compile(r"\bwhat(?:'s|\s+is)\s+the\s+meaning\s+of\s+(?P<w>.+)$", re.IGNORECASE),
    re.compile(r"\b(?:synonyms?|antonyms?|opposite)\s+(?:for|of)\s+(?P<w>.+)$", re.IGNORECASE),
    re.compile(r"\b(?:what(?:'s|\s+is)\s+(?:a|the)\s+)?(?:synonyms?|antonyms?|opposite)\s+(?P<w>[^\s]+)\s*$", re.IGNORECASE),
    re.compile(r"\b(?:define|definition\s+of|meaning\s+of|dictionary|spell|look\s*up|word)\s+(?:the\s+word\s+)?(?P<w>.+)$", re.IGNORECASE),
    re.compile(r"\bhow\s+do\s+you\s+spell\s+(?P<w>.+)$", re.IGNORECASE),
]


def extract_word(original: str) -> str:
    """The word being asked about (original case), or ''."""
    text = original.strip()
    for rx in _PATTERNS:
        m = rx.search(text)
        if m:
            word = m.group("w")
            break
    else:
        word = text
    word = word.strip().strip("?!.,;:\"'").strip()
    word = re.sub(r"^(?:the\s+word\s+|word\s+)", "", word, flags=re.IGNORECASE).strip()
    return word


def handle_dictionary(orch, c):
    """Handle dictionary lookup commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()

    word = extract_word(original)

    if not word or word.lower() in {"synonym", "synonyms", "antonym", "antonyms", "define", "meaning"}:
        orch.speak("What word should I look up?")
        return True

    if "synonym" in cmd:
        response = orch.dictionary.synonyms(word)
    elif "antonym" in cmd or "opposite" in cmd:
        response = orch.dictionary.antonyms(word)
    else:
        response = orch.dictionary.define(word)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

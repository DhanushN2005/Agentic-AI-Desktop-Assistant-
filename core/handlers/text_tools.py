import re

from utils.voice_parse import strip_wake

_COMMAND_PREFIX = re.compile(
    r"^(?:word count|character count|count words|count chars|reverse|uppercase|lowercase|title case|"
    r"sentence case|snake case|camel case|kebab case|remove duplicates?|sort lines|slugify|"
    r"wrap(?:\s+(?:at\s+)?\d+)?|extract emails|extract urls|extract numbers|find and replace)\b[\s:,-]*",
    re.IGNORECASE,
)
_OPEN_TO_CLOSE = {'"': '"', "“": "”", "‘": "’", "'": "'"}


def _edge_unquote(s: str):
    """Inner text when the WHOLE string is delimited by matching quote characters
    at both edges.  Apostrophes inside words (don't) are never quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] in _OPEN_TO_CLOSE and s[-1] == _OPEN_TO_CLOSE[s[0]]:
        return s[1:-1]
    return None


def _split_command(original: str):
    """(payload, keyword_scan_text): payload keeps its original case and quotes
    inside it; keywords are matched only against the text outside the payload."""
    # 1. a double-quoted (or curly-quoted) span anywhere
    m = re.search(r'(?<!\w)"([^"]*)"(?!\w)|“([^”]*)”', original)
    if m:
        payload = m.group(1) if m.group(1) is not None else m.group(2)
        return payload, (original[:m.start()] + " " + original[m.end():])
    # 2. leading command phrase, then the rest (possibly edge-quoted)
    pm = _COMMAND_PREFIX.match(original.strip())
    if pm:
        rest = original.strip()[pm.end():]
        inner = _edge_unquote(rest)
        return (inner if inner is not None else rest.strip()), pm.group(0)
    # 3. 'make this uppercase: hello'
    if ":" in original:
        head, _, tail = original.partition(":")
        inner = _edge_unquote(tail)
        return (inner if inner is not None else tail.strip()), head
    return original.strip(), original


def handle_text_tools(orch, c):
    """Handle text manipulation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    text, scan_raw = _split_command(original)
    cmd = scan_raw.lower()

    if not text and "count" not in cmd and "extract" not in cmd:
        orch.speak("What text should I process? Put it in quotes.")
        return True

    if "word count" in cmd or "count words" in cmd:
        response = orch.text_tools.word_count(text)
    elif "character count" in cmd or "count chars" in cmd:
        response = orch.text_tools.char_count(text)
    elif "reverse" in cmd:
        response = orch.text_tools.reverse(text)
    elif "uppercase" in cmd:
        response = orch.text_tools.uppercase(text)
    elif "lowercase" in cmd:
        response = orch.text_tools.lowercase(text)
    elif "title case" in cmd:
        response = orch.text_tools.title_case(text)
    elif "sentence case" in cmd:
        response = orch.text_tools.sentence_case(text)
    elif "snake case" in cmd:
        response = orch.text_tools.snake_case(text)
    elif "camel case" in cmd:
        response = orch.text_tools.camel_case(text)
    elif "kebab case" in cmd:
        response = orch.text_tools.kebab_case(text)
    elif "remove duplicate" in cmd:
        response = orch.text_tools.remove_duplicates(text)
    elif "sort lines" in cmd:
        response = orch.text_tools.sort_lines(text)
    elif "slugify" in cmd:
        response = orch.text_tools.slugify(text)
    elif "wrap" in cmd:
        width_match = re.search(r"wrap\s*(?:at\s*)?(\d+)", cmd)
        width = int(width_match.group(1)) if width_match else 80
        response = orch.text_tools.wrap(text, width)
    elif "extract emails" in cmd:
        response = orch.text_tools.extract_emails(text)
    elif "extract urls" in cmd:
        response = orch.text_tools.extract_urls(text)
    elif "extract numbers" in cmd:
        response = orch.text_tools.extract_numbers(text)
    else:
        response = orch.text_tools.word_count(text)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

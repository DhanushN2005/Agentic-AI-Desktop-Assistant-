import re

_MAX = 1000


def _count(cmd: str, default: int, pattern: str = r"(\d+)") -> int:
    m = re.search(pattern, cmd)
    return int(m.group(1)) if m else default


def handle_lorem(orch, c):
    """Handle lorem ipsum generation commands (counts limited to 0..1000)."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "list" in cmd or "numbered" in cmd:
        count = _count(cmd, 5)
        kind = "list"
    elif re.search(r"\bwords?\b", cmd):
        count = _count(cmd, 100)
        kind = "words"
    else:
        count = _count(cmd, 3, r"(\d+)\s*(?:paragraph|para)")
        kind = "paragraphs"

    if count < 1:
        orch.speak("Please ask for at least 1.")
        return True
    note = ""
    if count > _MAX:
        count = _MAX
        note = f" (limited to {_MAX})"

    if kind == "list":
        response = orch.lorem.generate_list(count)
    elif kind == "words":
        response = orch.lorem.generate_words(count)
    else:
        response = orch.lorem.generate(count)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(f"Generated {len(response)} characters of lorem ipsum text{note}.")
    return True

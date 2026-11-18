import re

from utils.voice_parse import strip_wake

_NUM = r"\d+(?:\.\d+)?"
_PERCENT = re.compile(rf"({_NUM})\s*(?:%|percent\b)", re.IGNORECASE)
_SPLIT_PATTERNS = [
    re.compile(rf"\bby\s+({_NUM})\b(?!\s*(?:%|percent))", re.IGNORECASE),
    re.compile(rf"\b({_NUM})\s*ways?\b", re.IGNORECASE),
    re.compile(rf"\b(?:split|share|divide)\s+(?:it\s+|this\s+)?(?:among\s+|between\s+|with\s+)?({_NUM})\b(?!\s*(?:%|percent))", re.IGNORECASE),
]


def _mask(text: str, span) -> str:
    return text[:span[0]] + " " * (span[1] - span[0]) + text[span[1]:]


def parse_tip_command(text: str):
    """Return dict(bill, percent, split, numbers) parsed from the ORIGINAL text."""
    working = text
    percent = None
    m = _PERCENT.search(working)
    if m:
        percent = float(m.group(1))
        working = _mask(working, m.span())

    split = None
    for rx in _SPLIT_PATTERNS:
        m = rx.search(working)
        if m:
            split = float(m.group(1))
            # only mask the number itself so a '$60' bill stays visible
            working = _mask(working, m.span(1))
            break

    bill = None
    m = re.search(rf"\$\s*({_NUM})", working)
    if m:
        bill = float(m.group(1))
    else:
        m = re.search(rf"\b(?:on|of|bill|for|total)\s+(?:is\s+)?\$?\s*({_NUM})", working, re.IGNORECASE)
        if m:
            bill = float(m.group(1))
        else:
            m = re.search(_NUM, working)
            if m:
                bill = float(m.group(0))
    return {"bill": bill, "percent": percent, "split": split,
            "numbers": [float(n) for n in re.findall(_NUM, text)]}


def handle_tip(orch, c):
    """Handle tip calculation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    text = strip_wake(c)
    cmd = text.lower()

    parsed = parse_tip_command(text)
    numbers = parsed["numbers"]
    tip_percent = parsed["percent"] if parsed["percent"] is not None else 15.0
    split_f = parsed["split"] if parsed["split"] is not None else 1.0

    if "from total" in cmd or "what percent" in cmd:
        if len(numbers) >= 2:
            response = orch.tip_calc.tip_from_total(numbers[0], numbers[1])
        else:
            response = "Provide total and bill amount."
    elif parsed["bill"] is None:
        response = "Provide a bill amount. Say 'tip 20% on $50' or 'split $60 by 3'."
    elif parsed["bill"] <= 0:
        response = "The bill must be more than zero."
    elif not 0 <= tip_percent <= 100:
        response = "A tip percentage must be between 0 and 100."
    elif split_f < 1 or split_f != int(split_f) or split_f > 100:
        response = "Split must be a whole number of people between 1 and 100."
    else:
        response = orch.tip_calc.calculate(parsed["bill"], tip_percent, int(split_f))

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

import ast
import operator
import re

from engines.system import SystemCtrl


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _extract_expr(c: str) -> str:
    text = c.lower()
    replacements = [
        (r"\bto the power of\b", "**"),
        (r"\bpower of\b", "**"),
        (r"\bsquared\b", "**2"),
        (r"\bcubed\b", "**3"),
        (r"\bmultiplied by\b", "*"),
        (r"\bdivided by\b", "/"),
        (r"\bpercent of\b", "*0.01*"),
        (r"\bplus\b", "+"),
        (r"\bminus\b", "-"),
        (r"\btimes\b", "*"),
        (r"\binto\b", "*"),
        (r"\bover\b", "/"),
        (r"\bmodulo\b", "%"),
        (r"\bmod\b", "%"),
        (r"\bx\b", "*"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return "".join(re.findall(r"\d+\.?\d*|\*\*|[+\-*/%()]", text))


def handle_calc(orch, c):
    expr = _extract_expr(c)
    if not expr:
        orch.speak("I couldn't find any numbers to calculate.")
        return True
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        orch.speak(f"That equals {result}.")
        orch.ctx.update(last_response=str(result))
    except Exception:
        orch.speak("I couldn't calculate that. Please try a simpler math question.")
    return True


def handle_status(orch, c):
    try:
        cpu, ram = SystemCtrl.cpu_ram()
        batt = SystemCtrl.battery_status()
        orch.speak(f"CPU is at {cpu} percent, RAM at {ram} percent, battery at {batt}.")
    except Exception:
        orch.speak("I couldn't read the system status right now.")
    return True


def handle_memory(orch, c):
    c_l = c.lower().strip()

    if any(x in c_l for x in ["what do you know", "list memory", "what did i say", "what did i save"]):
        facts = orch.memory.all_facts()
        if not facts:
            orch.speak("My memory is empty. Tell me something to remember.")
        else:
            orch.speak("Here is what I remember. " + ". ".join(f"{k}: {v}" for k, v, _ in facts))
        return True

    if c_l.startswith("forget "):
        key = c[7:].strip()
        if key:
            orch.memory.forget(key)
            orch.speak(f"Forgotten '{key}'.")
        else:
            orch.speak("What should I forget?")
        return True

    rest = c[len("remember that "):].strip() if c_l.startswith("remember that ") else (
        c[len("remember "):].strip() if c_l.startswith("remember ") else c_l
    )

    if " are " in rest or " is " in rest:
        sep = " are " if " are " in rest else " is "
        key, _, value = rest.partition(sep)
        key, value = key.strip(), value.strip()
        if key and value:
            orch.memory.store(key, value, cat="user")
            orch.speak(f"Got it. I'll remember {key}.")
            return True

    key = c[7:].strip() if c_l.startswith("recall ") else rest
    val = orch.memory.recall(key) if key else None
    if val is not None:
        orch.speak(f"{key} is {val}.")
    else:
        orch.speak(f"I don't remember anything about '{key}'.")
    return True


def handle_translate(orch, c):
    m = re.search(r"^translate\s+(.+?)\s+to\s+([a-zA-Z][a-zA-Z \-]*)$", c.strip(), re.IGNORECASE)
    if not m:
        orch.speak("Say something like 'translate hello to Spanish'.")
        return True
    text, lang = m.group(1).strip(), m.group(2).strip()
    orch.speak(f"Translating to {lang}.")
    result = orch.brain.translate(text, lang)
    orch.ctx.update(last_response=result)
    orch.speak(result)
    return True

import logging
import re

from engines.password_gen import MAX_LENGTH, MIN_LENGTH
from utils.voice_parse import strip_wake

_CHECK_RE = re.compile(
    r"(?:check|strength|evaluate|how\s+(?:strong|secure)(?:\s+is)?)\s+"
    r"(?:the\s+|my\s+|this\s+)*(?:password\s+)?(?:is\s+)?"
    r"(?:\"(?P<dq>[^\"]+)\"|'(?P<sq>[^']+)'|(?P<bare>\S+))",
    re.IGNORECASE,
)


def _show_privately(orch, password: str) -> bool:
    """Put a generated secret on screen / clipboard only - never in speech,
    ctx.last_response or chat memory.  Returns True if clipboard copy worked."""
    copied = False
    try:
        import pyperclip
        pyperclip.copy(password)
        copied = True
    except Exception as _e:
        logging.debug("[password] clipboard unavailable: %s: %s", type(_e).__name__, _e)
    try:
        orch.send_to_ui("SAY", f"Generated password: `{password}`")
    except Exception as _e:
        logging.debug("[password] UI unavailable: %s: %s", type(_e).__name__, _e)
    return copied


def handle_password(orch, c):
    """Handle password generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()
    # never keep the user's typed password in conversation context
    safe_query = "password request"

    if "check" in cmd or "strength" in cmd or "evaluate" in cmd or "how strong" in cmd or "how secure" in cmd:
        pw_match = _CHECK_RE.search(original)  # ORIGINAL text: case preserved
        if pw_match:
            pw = pw_match.group("dq") or pw_match.group("sq") or pw_match.group("bare")
            result = orch.password_gen.strength_check(pw)
            response = f"Password strength: {result['level']} (score {result['score']}/6)"
            if result["feedback"]:
                response += ". Tips: " + ", ".join(result["feedback"])
        else:
            response = "What password should I check?"
        orch.ctx.update(last_response=response, query=safe_query)
        orch.speak(response)
        return True

    if "passphrase" in cmd:
        length_match = re.search(r"(\d+)\s*words?", cmd)
        words = int(length_match.group(1)) if length_match else 4
        try:
            phrase = orch.password_gen.generate_passphrase(words)
        except ValueError as e:
            response = str(e)
            orch.ctx.update(last_response=response, query=safe_query)
            orch.speak(response)
            return True
        copied = _show_privately(orch, phrase)
        response = "I generated a passphrase " + ("and copied it to your clipboard." if copied else "and posted it on your screen.")
        orch.ctx.update(last_response=response, query=safe_query)
        orch.speak(response)
        return True

    length_match = re.search(r"(\d+)\s*(?:char|digit|letter|length|long)", cmd)
    length = int(length_match.group(1)) if length_match else 16
    if not MIN_LENGTH <= length <= MAX_LENGTH:
        response = f"A password needs to be between {MIN_LENGTH} and {MAX_LENGTH} characters long."
        orch.ctx.update(last_response=response, query=safe_query)
        orch.speak(response)
        return True

    no_symbols = "no symbol" in cmd or "without symbol" in cmd or "letters only" in cmd
    try:
        password = orch.password_gen.generate(length=length, use_symbols=not no_symbols)
    except ValueError as e:
        response = str(e)
        orch.ctx.update(last_response=response, query=safe_query)
        orch.speak(response)
        return True
    copied = _show_privately(orch, password)
    response = (f"I generated a {length}-character password "
                + ("and copied it to your clipboard." if copied else "and posted it on your screen."))
    orch.ctx.update(last_response=response, query=safe_query)
    orch.speak(response)
    return True

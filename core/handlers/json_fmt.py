import logging
import re

from utils.voice_parse import strip_wake


def handle_json(orch, c):
    """Handle JSON formatting commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    # JSON payload comes from the ORIGINAL text so keys/values keep their case.
    json_text = re.search(r'(\{.*\}|\[.*\])', original, re.DOTALL)
    if not json_text:
        # Try to get text from clipboard or context
        try:
            import pyperclip
            json_text_str = pyperclip.paste()
            if json_text_str and (json_text_str.strip().startswith('{') or json_text_str.strip().startswith('[')):
                json_text_str = json_text_str.strip()
            else:
                orch.speak("I need JSON text to process. Paste or provide valid JSON.")
                return True
        except Exception as _e:
            logging.debug("[core/handlers/json_fmt.py:22] Swallowed exception: %s: %s", type(_e).__name__, _e)
            orch.speak("I need JSON text to process.")
            return True
        cmd = original.lower()
    else:
        json_text_str = json_text.group(1)
        # keywords come only from the words around the JSON, never from its content
        cmd = (original[:json_text.start()] + " " + original[json_text.end():]).lower()

    if "format" in cmd or "pretty" in cmd or "indent" in cmd:
        response = orch.json_formatter.format_json(json_text_str)
    elif "minify" in cmd or "compact" in cmd or "compress" in cmd:
        response = orch.json_formatter.minify_json(json_text_str)
    elif "validate" in cmd or "check" in cmd:
        response = orch.json_formatter.validate_json(json_text_str)
    elif "info" in cmd or "describe" in cmd:
        response = orch.json_formatter.json_info(json_text_str)
    elif "keys" in cmd:
        response = orch.json_formatter.extract_keys(json_text_str)
    elif "flatten" in cmd:
        response = orch.json_formatter.flatten_json(json_text_str)
    else:
        response = orch.json_formatter.format_json(json_text_str)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

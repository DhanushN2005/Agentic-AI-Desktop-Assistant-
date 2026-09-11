import re
import json


def handle_json(orch, c):
    """Handle JSON formatting commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Try to find JSON in the command
    json_text = re.search(r'(\{.*\}|\[.*\])', cmd, re.DOTALL)
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
        except Exception:
            orch.speak("I need JSON text to process.")
            return True
    else:
        json_text_str = json_text.group(1)

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

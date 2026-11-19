import os
import re


def _screen_prompt(c: str) -> str:
    """Turn what the user said into the question the vision model should answer."""
    low = (c or "").lower()
    if re.search(r"\bsummari[sz]e\b|\bsummary\b|\bin short\b|\bbriefly\b", low):
        return ("Summarize what is on my screen in 2-3 short sentences: which app or page is open and "
                "what I appear to be doing.")
    if re.search(r"\berror\b|\bwhat'?s wrong\b|\bproblem\b", low):
        return "Look at my screen. If there is an error or problem, explain it simply and say how to fix it."
    if low.strip() and not re.fullmatch(r"(?:please\s+)?(?:analy[sz]e|describe|check|look\s+at|read|what'?s\s+on)\s+(?:my\s+|the\s+)?screen", low.strip()):
        # the user said something specific ("check my screen, the tab says wrong"): answer THAT
        return (f'The user said: "{c.strip()}". Look at their screen and respond to exactly that, '
                "concisely, saying what you actually see.")
    return ("Describe what is on my screen right now: the main app or page, and anything important "
            "(text, errors, notifications). Be concise.")


def handle_vision(orch, intent, c):
    if intent == "vision_capture":
        res = orch.vision.capture_screen()
        if "ERROR" in str(res):
            orch.speak("I couldn't take the screenshot. " + str(res).replace("ERROR:", "").strip())
        else:
            orch.ctx.update(screenshot=res)
            if hasattr(orch, "push_undo"):
                orch.push_undo("the screenshot", lambda: orch.vision.delete_last_screenshot())
            orch.speak(f"I took a screenshot and saved it as {os.path.basename(res)} in "
                       f"{os.path.dirname(res) or 'your captures folder'}. "
                       "Say 'show screenshot' to open it, or 'analyze my screen' and I'll tell you what's on it.")
    elif intent == "vision_show":
        orch.speak(orch.vision.show_last_screenshot())
    elif intent == "vision_analyze":
        low = (c or "").lower()
        if re.search(r"\bread\b", low) and "summar" not in low:
            text = orch.vision.read_screen_text()
            orch.speak(text if text else "I couldn't find any readable text on the screen.")
        else:
            orch.speak(orch.vision.analyze_screen(orch.brain, _screen_prompt(c)))
    elif intent == "vision_debug":
        orch.speak(orch.dev.debug_screen())
    return True


def handle_camera_capture(orch):
    orch.speak(orch.vision.launch_camera())
    return True

import re
import webbrowser


def _wants_close(cl: str) -> bool:
    return bool(re.search(r"\b(?:close|stop|exit|quit|end|shut|turn off|disable|kill)\b", cl))


def handle_vision_mode(orch, c):
    """"open vision mode" opens the dashboard on its Orb panel; "close vision mode" closes the panel."""
    vm = getattr(orch, "vision_mode", None)
    if vm is None:
        orch.speak("Vision mode isn't available in this build.")
        return True
    cl = (c or "").lower()

    if _wants_close(cl):
        # Any open dashboard hides the orb and releases its camera; nothing to kill.
        orch.send_to_ui("PANEL", "close")
        orch.speak("Vision mode closed.")
        return True

    why = vm.problem()
    if why:
        orch.speak(why)
        return True

    from core.handlers.system import ensure_web_bridge
    try:
        if not ensure_web_bridge(orch):
            orch.speak("I couldn't start the web UI bridge, so vision mode can't open.")
            return True
        webbrowser.open(vm.url)
    except Exception as e:  # the browser or the bridge launch can fail on odd setups
        orch.speak(f"I couldn't open vision mode: {str(e)[:100]}")
        return True
    # A dashboard that is already open switches to the orb too.
    orch.send_to_ui("PANEL", "orb")
    orch.speak("Vision mode is open in your browser. Press G there to turn on hand gestures, "
               "and allow camera access.")
    return True

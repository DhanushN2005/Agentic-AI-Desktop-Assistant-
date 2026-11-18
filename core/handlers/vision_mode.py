import re
import threading
import webbrowser


def _wants_stop(cl: str) -> bool:
    return bool(re.search(r"\b(?:close|stop|exit|quit|end|shut|turn off|disable|kill)\b", cl))


def handle_vision_mode(orch, c):
    """"open vision mode" starts the hand-gesture orb UI; "close vision mode" stops it."""
    vm = getattr(orch, "vision_mode", None)
    if vm is None:
        orch.speak("Vision mode isn't available in this build.")
        return True
    cl = (c or "").lower()

    if _wants_stop(cl):
        orch.speak("Vision mode closed." if vm.stop() else "Vision mode isn't running.")
        return True

    if vm.is_running():
        webbrowser.open(vm.url)
        orch.speak(f"Vision mode is already running. I've brought it up at {vm.url}. Press G to turn on hand gestures.")
        return True
    if vm.is_busy():
        orch.speak("Vision mode is still starting. Give it a moment.")
        return True
    why = vm.problem()
    if why:
        orch.speak(why)
        return True

    orch.speak("Starting vision mode.")

    def _go():
        ok, msg = vm.start(say=lambda m: orch.speak(m))
        if not ok:
            orch.speak(msg)
            return
        webbrowser.open(msg)
        orch.speak("Vision mode is ready and open in your browser. Press G to turn on hand gestures, "
                   "and allow camera access.")

    threading.Thread(target=_go, name="vision-mode-start", daemon=True).start()
    return True

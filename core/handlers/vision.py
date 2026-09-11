def handle_vision(orch, intent, c):
    if intent == "vision_capture":
        res = orch.vision.capture_screen()
        if "ERROR" not in res:
            orch.ctx.update(screenshot=res)
            orch.speak("Snap saved.")
    elif intent == "vision_show":
        orch.speak(orch.vision.show_last_screenshot())
    elif intent == "vision_analyze":
        orch.speak(orch.vision.analyze_screen(orch.brain))
    elif intent == "vision_debug":
        orch.speak(orch.dev.debug_screen())
    return True


def handle_camera_capture(orch):
    orch.speak(orch.vision.launch_camera())
    return True

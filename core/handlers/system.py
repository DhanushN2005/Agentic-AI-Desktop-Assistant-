import os
import re
import time

from engines.system import SystemCtrl
from utils.config import Config
from utils.helpers import get_numbers


def handle_undo(orch, c):
    if not orch.undo_stack:
        orch.speak("Nothing to undo.")
        return True
    action, data = orch.undo_stack.pop()
    if action == "mode":
        orch.send_to_ui("MODE", data)
        orch.speak(f"Reverted mode to {data}.")
    elif action == "open":
        SystemCtrl.close_app(data)
        orch.speak(f"Closed {data}.")
    elif action == "screenshot":
        orch.speak(orch.vision.delete_last_screenshot())
    return True


def handle_mode(orch, c, silent):
    mode = re.sub(r"(set mode to|set mode|switch mode to|switch mode|change mode to|change mode|mode to| flexie| mode)", "", c).strip()
    if not mode:
        modes_str = ", ".join(Config.MODES)
        orch.speak(f"Available modes: {modes_str}. Which mode would you like?")
        return True
    if mode in Config.MODES:
        orch.current_mode = mode  # UPDATE INTERNAL MODE
        orch.send_to_ui("MODE", mode)
        orch.speak(f"System Optimized for {mode}.")
    else:
        orch.speak(f"Unknown mode '{mode}'. Available modes: {', '.join(Config.MODES)}.")
    return True


def handle_exit(orch):
    orch.yt.cleanup()
    orch.browser.cleanup()
    orch.speak("Goodbye!")
    orch.send_to_ui("QUIT", "NOW")
    time.sleep(0.5)
    os._exit(0)


def handle_power(orch, c):
    # High-Level Security for Power Actions
    destructive_triggers = [
        "shutdown", "restart", "turn off", "power off", "device off",
        "turn my device off", "turn pc off", "turn off pc",
        "turn of device", "turn device of", "turn my device of"
    ]
    if any(x in c for x in destructive_triggers):
        orch.speak("Security protocol active. Please provide the authorization code to proceed with system power action.")
        auth = orch.voice.listen(timeout=5)
        if auth and "code red" in auth.lower():
            orch.speak("Authorization confirmed. Initiating power command.")
            SystemCtrl.power(c)
        else:
            orch.speak("Authorization failed. Power command aborted.")
    else:
        # Lower risk commands like 'lock' or 'sleep'
        orch.speak("Executing system power command.")
        SystemCtrl.power(c)
    return True


def handle_snap(orch, c):
    direction = "left"
    if "right" in c:
        direction = "right"
    elif "top" in c or "up" in c:
        direction = "top"
    elif "bottom" in c or "down" in c:
        direction = "bottom"
    elif "full" in c or "max" in c or "maximize" in c:
        direction = "full"
    elif "minimize" in c or "hide" in c:
        direction = "minimize"

    app_target = None
    for app in ["notepad", "chrome", "edge", "spotify", "vscode", "calculator", "word", "document"]:
        if app in c:
            app_target = app
            break

    res = SystemCtrl.snap_window(direction, app_target)
    orch.speak(res)
    return True


def handle_volume(orch, c, silent):
    v = get_numbers(c)[0] if get_numbers(c) else 50
    SystemCtrl.set_volume(v)
    if not silent:
        orch.speak(f"Volume set to {v} percent.")
    return True


def handle_brightness(orch, c, silent):
    v = get_numbers(c)[0] if get_numbers(c) else 70
    SystemCtrl.set_brightness(v)
    if not silent:
        orch.speak(f"Brightness set to {v} percent.")
    return True


def handle_mode_prefix(orch, c, silent):
    mode = c.replace("mode ", "").strip()
    orch.current_mode = mode
    if not silent:
        orch.speak(f"Switched to {mode} mode.")
    return True


def handle_app_op(orch, c, silent):
    # REDIRECTION: If the command contains search-like keywords, redirect to search intent
    if any(x in c for x in ["search", "google", "find ", "who is", "what is", "earch", "arch"]):
        search_cmd = re.sub(r"^(open|launch|start)\s+(chrome|browser|google|edge)\s+(?:search\s+)?", "search for ", c).strip()
        if "search for" not in search_cmd:
            search_cmd = "search for " + search_cmd
        orch.handle_command(search_cmd, is_subcommand=True, silent=silent)
        return True

    target = re.sub(r"(open|run|launch|start|close|kill|app|the)", "", c).strip()
    if "close" in c or "kill" in c:
        SystemCtrl.close_app(target)
        orch.speak(f"Closed {target}.")
    else:
        # Context chaining: check if we should pass a target path
        t_path = None
        if "same" in c or " it" in c or "this" in c or "that" in c:
            t_path = orch.ctx.last_path

        res = orch.files.open_item(target, target_path=t_path)
        if "NOT_FOUND" not in res:
            orch.ctx.update(app=target)
        orch.speak(res)
    return True


def handle_save_active(orch):
    title = SystemCtrl.get_active_window_title()
    SystemCtrl.save_active_file()
    orch.speak(f"Saved your work in {title}.")
    return True


def handle_auto_save(orch, c):
    if "stop" in c or "disable" in c:
        orch.auto_save_enabled = False
        orch.speak("Auto-save disabled.")
    else:
        orch.auto_save_enabled = True
        orch.speak("Auto-save is now active. I will save your work every 60 seconds.")
    return True


def handle_comm(orch, c):
    if "whatsapp" in c:
        target = re.sub(r"(whatsapp|message|send|to)", "", c).strip()
        if target:
            orch.speak(f"Opening WhatsApp for {target}...")
            orch.browser.navigate(f"https://web.whatsapp.com/send?phone={target}")
        else:
            orch.speak("Opening WhatsApp Web.")
            orch.files.open_item("whatsapp")
    elif any(x in c for x in ["send mail", "send email"]):
        to_match = re.search(r"to\s+([^\s]+@[^\s]+)", c)
        if to_match:
            to_addr = to_match.group(1)
            orch.speak(f"Composing email to {to_addr}. What should I write?")
            body = orch.voice.listen(timeout=10)
            if body and body != "[error_offline]" and body.strip():
                orch.speak(orch.email.send_email(to_addr, "Message from Flexie", body))
            else:
                orch.speak("Cancelled email composition.")
        else:
            orch.speak("Who should I send the email to? Please say the email address.")
            to_addr = orch.voice.listen(timeout=8)
            if to_addr and "@" in to_addr:
                orch.speak("What should the email say?")
                body = orch.voice.listen(timeout=10)
                if body:
                    orch.speak(orch.email.send_email(to_addr.strip(), "Message from Flexie", body))
        return True
    elif "email" in c:
        # Check inbox via EmailEngine first
        try:
            emails = orch.email.get_unread_emails(count=3)
            if emails and "credentials are missing" not in emails[0].lower():
                for e in emails:
                    orch.speak(e)
                return True
        except: pass
        orch.speak("Opening your email composer.")
        orch.files.open_item("gmail")
    return True


def handle_voice(orch, c):
    if "test" in c or "can you hear me" in c:
        orch.speak("I can hear you loud and clear, Dhanush. If you can hear me too, then our voice systems are working perfectly.")
    elif "diagnose" in c or "check" in c:
        orch.speak("Starting voice hardware diagnostic.")
        try:
            import pyttsx3
            test_engine = pyttsx3.init()
            voices = test_engine.getProperty('voices')
            orch.speak(f"Found {len(voices)} voices on this system.")
            for i, v in enumerate(voices):
                msg = f"Testing voice {i}: {v.name}"
                print(f"[Voice Test] {msg}")
                test_engine.setProperty('voice', v.id)
                test_engine.say(f"This is voice number {i}, also known as {v.name}. Can you hear me?")
                test_engine.runAndWait()
            orch.speak("Diagnostic complete. Check the terminal for voice details.")
        except Exception as e:
            orch.speak(f"Diagnostic failed: {e}")
    elif "hindi" in c:
        orch.voice.lang = "hi-IN"
        orch.speak("अब मैं हिंदी समझ सकती हूँ।")
    elif "english" in c:
        orch.voice.lang = "en-IN"
        orch.speak("Language switched to English.")
    elif "faster" in c:
        orch.speak("Speaking faster now.")
    return True

import logging
import os
import re
import subprocess
import sys
import time
import webbrowser

from engines.self_awareness import MODE_MAP
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


def _mode_speech():
    return "; ".join(f"{n} — {d}" for n, d in MODE_MAP.items())


def handle_mode(orch, c, silent):
    mode = re.sub(r"(set mode to|set mode|switch mode to|switch mode|change mode to|change mode|mode to| flexie| mode)", "", c).strip()
    if not mode:
        orch.speak(f"There are {len(Config.MODES)} modes: {_mode_speech()}. Which one would you like?")
        return True
    if mode in Config.MODES:
        orch.current_mode = mode  # UPDATE INTERNAL MODE
        orch.send_to_ui("MODE", mode)
        orch.speak(f"System optimized for {mode} mode, {MODE_MAP[mode]}")
    else:
        orch.speak(f"Unknown mode '{mode}'. There are {len(Config.MODES)} modes: {_mode_speech()}.")
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
    nums = get_numbers(c)
    curr = SystemCtrl.get_volume()
    is_down = any(x in c for x in ["down", "lower", "decrease", "quieter", "reduce", "drop"])
    is_up = any(x in c for x in ["up", "raise", "increase", "louder", "higher", "boost"])

    if "mute" in c and "unmute" not in c:
        v = 0
    elif "unmute" in c:
        v = 30 if curr == 0 else curr
    elif nums:
        amt = nums[0]
        # Relative adjustment: e.g. "down volume by 20", "volume down 20", "turn volume up by 15"
        if "by" in c or (is_down and "to" not in c) or (is_up and "to" not in c):
            if is_down:
                v = max(0, curr - amt)
            elif is_up:
                v = min(100, curr + amt)
            else:
                v = max(0, min(100, amt))
        else:
            # Absolute target: e.g. "set volume 40", "volume to 70", "volume 50"
            v = max(0, min(100, amt))
    elif is_up or "max" in c:
        v = 100 if "max" in c else min(100, curr + 5)
    elif is_down or "min" in c:
        v = 0 if "min" in c else max(0, curr - 5)
    else:
        v = 50
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
    if mode in Config.MODES:
        orch.current_mode = mode
        orch.send_to_ui("MODE", mode)
        if not silent:
            orch.speak(f"Switched to {mode} mode.")
    else:
        orch.speak(f"Unknown mode '{mode}'. There are {len(Config.MODES)} modes: {_mode_speech()}.")
    return True


_BROWSER_APPS = ("chrome", "edge", "firefox", "browser", "opera", "brave")


_BROWSER_EXE = {"chrome": "chrome", "edge": "msedge", "firefox": "firefox"}


def _open_search_in_browser(orch, browser: str, query: str, silent: bool) -> bool:
    """Open a Google search for ``query`` in the named browser and say what happened."""
    from urllib.parse import quote_plus
    url = "https://www.google.com/search?q=" + quote_plus(query)
    exe = _BROWSER_EXE.get(browser)
    opened = False
    if exe and sys.platform == "win32":
        try:
            # fixed argv, no shell string: the URL is percent-encoded so it cannot inject anything
            subprocess.Popen(["cmd.exe", "/c", "start", "", exe, url],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            opened = True
        except OSError as e:
            logging.debug("browser launch failed: %s", e)
    if not opened:
        opened = bool(webbrowser.open(url))
    label = browser if browser in _BROWSER_EXE else "your browser"
    orch.ctx.update(app=browser)
    if not silent:
        orch.speak(f"Searching Google for {query} in {label}." if opened
                   else f"I couldn't open {label} to search for {query}.")
    return opened


def _clean_app_target(cl: str) -> str:
    """Reduce a spoken open/close request to the app name.

    "close the chrome that u opened", "close all chromes you have opened" and "close chrome windows"
    all name just "chrome"; filler words and relative clauses are dropped.
    """
    t = re.sub(r"\b(open|run|launch|start|close|kill|quit|exit|app|apps|the|a|my|please|for me)\b", " ", cl)
    # relative clauses: "that u opened", "which you have opened", "you started"
    t = re.sub(r"\b(?:that|which)?\s*\b(?:you|u|i|we)\s+(?:have\s+|had\s+|just\s+|already\s+)?"
               r"(?:opened|started|launched|run|ran)\b", " ", t)
    t = re.sub(r"\b(?:windows?|tabs?|instances?|that|which|opened|running|currently|now)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # "all chromes" -> "chrome": drop a trailing plural s on a known app/browser name
    m = re.fullmatch(r"(?:all\s+)?(?:of\s+)?(\w+?)s", t)
    if m and (m.group(1) in _BROWSER_APPS or m.group(1) in getattr(Config, "APPS", {})):
        return m.group(1)
    parts = t.split()
    if len(parts) == 2 and parts[0] == "all" and parts[1] not in ("apps", "windows", "programs", "applications", "everything"):
        return parts[1]
    return t


def _open_browser_only(orch, browser_name: str, silent: bool):
    """Open a browser app and mark context. Returns True."""
    res = None
    try:
        res = orch.files.open_item(browser_name)
    except Exception as _e:
        logging.debug("[handle_app_op] open_item error: %s", _e)

    _browser_names = ("chrome", "edge", "firefox", "browser", "opera", "brave")
    if any(b in browser_name for b in _browser_names) and hasattr(orch.ctx, "set_browser_open"):
        orch.ctx.set_browser_open(browser_name)
    orch.ctx.update(app=browser_name)

    if res and "NOT_FOUND" not in str(res):
        if not silent:
            orch.speak(res)
    else:
        # Chrome may already be open — just acknowledge
        if not silent:
            orch.speak("Chrome is ready for you.")
    return True


def handle_app_op(orch, c, silent):
    cl = c.lower()

    # ── Multi-step: "open chrome play X [in youtube]" / "open chrome and play X" ──
    # Match "play/watch" anywhere after the browser name (with or without "in youtube")
    yt_follow = re.search(r"\b(?:play|watch)\s+(.+)", cl)
    if yt_follow and any(b in cl for b in _BROWSER_APPS):
        # Make sure the play comes AFTER the browser mention, not before
        browser_pos = min((cl.find(b) for b in _BROWSER_APPS if b in cl), default=-1)
        play_pos = cl.find(yt_follow.group(0))
        if browser_pos != -1 and play_pos > browser_pos:
            browser = next((b for b in _BROWSER_APPS if b in cl), "chrome")
            _open_browser_only(orch, browser, silent=True)
            play_cmd = yt_follow.group(0).strip()  # e.g. "play tamil song in youtube"
            res = orch.handle_command(play_cmd, is_subcommand=True, silent=silent)
            return True if res is None else bool(res)

    # ── Multi-step: "open chrome search for X" ──────────────────────────────
    if any(x in cl for x in ["search", "google", "find ", "who is", "what is"]):
        browser = next((b for b in _BROWSER_APPS if b in cl), None)
        direct = re.match(
            r"^(?:please\s+)?(?:open|launch|start)\s+(?:the\s+)?(?:chrome|edge|firefox|browser)\s+(?:and\s+)?"
            r"(?:search\s+(?:for\s+)?|google\s+|look\s+up\s+|find\s+)(.+)$", cl.strip())
        if browser and direct and direct.group(1).strip():
            # "open chrome and search for X": put the search straight into that browser
            # (instead of a slow multi-tab research pass that reads an essay aloud).
            return _open_search_in_browser(orch, browser, direct.group(1).strip(), silent)
        if browser:
            _open_browser_only(orch, browser, silent=True)
        search_cmd = re.sub(
            r"^(?:open|launch|start)\s+(?:the\s+)?(?:chrome|browser|google|edge|firefox)\s+(?:and\s+)?(?:search\s+)?",
            "search for ", cl
        ).strip()
        if not search_cmd.startswith("search for"):
            search_cmd = "search for " + search_cmd
        res = orch.handle_command(search_cmd, is_subcommand=True, silent=silent)
        return True if res is None else bool(res)

    # ── Simple: "open chrome" / "open edge" ────────────────────────────────
    browser_hit = next((b for b in _BROWSER_APPS if b in cl), None)
    is_close = "close" in cl or "kill" in cl

    if browser_hit and not is_close:
        return _open_browser_only(orch, browser_hit, silent=silent)

    # ── General app open / close ────────────────────────────────────────────
    target = (_clean_app_target(cl) if is_close
              else re.sub(r"\b(open|run|launch|start|close|kill|app|the)\b", "", cl).strip())
    # Reject filler-only targets produced by compound-command splitting ("open for me", "open it")
    _FILLERS = {"", "me", "for me", "it", "this", "that", "us", "please", "for", "now"}
    if target in _FILLERS:
        if not silent:
            orch.speak("What app would you like me to open?")
        return True

    if is_close:
        if SystemCtrl.is_close_all(target):
            if orch.voice.confirm("Close all your open apps? Unsaved work may be lost."):
                closed = SystemCtrl.close_all_known_apps()
                if not silent:
                    orch.speak(f"Closed {', '.join(closed)}." if closed else "I did not find any known apps to close.")
            elif not silent:
                orch.speak("Okay, I left your apps open.")
            return True
        closed = SystemCtrl.close_app(target)
        if not silent:
            orch.speak("I couldn't find a running app called " + target + "." if closed is False else f"Closed {target}.")
    else:
        t_path = None
        if "same" in cl or " it" in cl or "this" in cl or "that" in cl:
            t_path = orch.ctx.last_path

        try:
            res = orch.files.open_item(target, target_path=t_path)
        except Exception as _e:
            logging.debug("[handle_app_op] open_item error: %s", _e)
            res = None

        if res and "NOT_FOUND" not in str(res):
            orch.ctx.update(app=target)
            if any(b in target for b in _BROWSER_APPS) and hasattr(orch.ctx, "set_browser_open"):
                orch.ctx.set_browser_open(target)
            if not silent:
                orch.speak(res)
        else:
            if not silent:
                orch.speak(f"I couldn't find {target} on your system. Is it installed?")
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
    elif any(x in c for x in ["reply to email", "reply to mail", "reply email", "reply mail", "reply to last email"]):
        # Extract reply body if provided inline: e.g. "reply to email saying thank you"
        saying_match = re.search(r"(?:saying|that|with)\s+(.+)", c)
        inline_body = saying_match.group(1).strip() if saying_match else None

        # Fetch latest email to determine sender
        detailed = orch.email.get_unread_emails_detailed(count=1)
        sender = None
        subject = None
        if detailed and "error" not in detailed[0]:
            sender = detailed[0].get("from")
            subject = detailed[0].get("subject")

        to_addr = sender or "recipient"
        if not inline_body:
            orch.speak(f"Replying to {to_addr}. What should the reply say?")
            inline_body = orch.voice.listen(timeout=10)

        if inline_body and inline_body != "[error_offline]" and inline_body.strip():
            res = orch.email.reply_email(to_addr, inline_body, subject=subject)
            orch.speak(res)
        else:
            orch.speak("Reply cancelled.")
        return True
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
    elif "email" in c or "mail" in c:
        # Check inbox via EmailEngine first
        try:
            emails = orch.email.get_unread_emails(count=3)
            if emails and "credentials are missing" not in emails[0].lower():
                for e in emails:
                    orch.speak(e)
                return True
        except Exception as _e:
            logging.debug("[core/handlers/system.py:199] Swallowed exception: %s: %s", type(_e).__name__, _e)
        orch.speak("Opening your email composer.")
        orch.files.open_item("gmail")
    return True


def handle_voice(orch, c):
    if "test" in c or "can you hear me" in c:
        orch.speak(f"I can hear you loud and clear, {Config.USER_NAME}. If you can hear me too, then our voice systems are working perfectly.")
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
            logging.debug("[core/handlers/system.py:222] Swallowed exception: %s: %s", type(e).__name__, e)
            orch.speak(f"Diagnostic failed: {e}")
    elif "hindi" in c:
        orch.voice.lang = "hi-IN"
        orch.speak("अब मैं हिंदी समझ सकती हूँ।")
    elif "english" in c:
        orch.voice.lang = "en-IN"
        orch.speak("Language switched to English.")
    elif "faster" in c:
        orch.speak("Speaking faster now.")
    elif "run command" in c or "execute" in c:
        return handle_run_cmd(orch, c)
    elif "open web ui" in c or "start web ui" in c or "activate web" in c:
        return handle_open_web_ui(orch, c)
    return True


def handle_run_cmd(orch, c):
    """Handle voice commands to run CMD commands."""
    # Extract the command after "run command" or "execute"
    trigger_words = ["run command", "execute", "run cmd"]
    for word in trigger_words:
        c = c.replace(word, "").strip()

    # Get the CMD command
    cmd = c.strip()
    if not cmd:
        orch.speak("Please specify a command to run. Examples: dir, cd, type filename.")
        return True

    # Execute the command
    result = SystemCtrl.run_cmd(cmd)
    orch.speak(result)
    return True


def handle_open_web_ui(orch, c):
    """Open the web UI dashboard, auto-starting the bridge if it isn't running.

    Whatever you type (or speak) in the dashboard is relayed verbatim to the
    orchestrator and handled exactly like a normal command.
    """
    try:
        import socket

        url = "http://localhost:8766"

        def _bridge_alive() -> bool:
            # Probe the WebSocket port the bridge listens on (8765).
            try:
                with socket.create_connection(("127.0.0.1", 8765), timeout=0.5):
                    return True
            except OSError:
                return False

        if not _bridge_alive():
            orch.speak("Starting the web UI bridge.")
            bridge_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "interface",
                "web_ui_bridge.py",
            )
            subprocess.Popen(
                [sys.executable, bridge_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Wait up to ~5s for the bridge's HTTP/WS server to come up.
            for _ in range(25):
                if _bridge_alive():
                    break
                time.sleep(0.2)

        webbrowser.open(url)
        orch.speak("Web UI opened. Type or speak anything in the dashboard and I will handle it.")
        return True
    except Exception as e:
        orch.speak(f"Failed to open web UI: {str(e)[:100]}")
        return True

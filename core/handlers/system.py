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
    if action == "fn":
        label, fn, made = data
        if time.time() - made > 900:
            orch.speak(f"That was a while ago, so I've left {label} as it is.")
            return True
        try:
            orch.speak(fn() or f"Undid {label}.")
        except Exception as e:                    # noqa: BLE001 - say what failed instead of staying silent
            orch.speak(f"I couldn't undo {label}. {type(e).__name__}.")
        return True
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
    if mode not in Config.MODES:
        # "switch to hacker mode", "activate hacker mode", "enable minimal mode": find the mode name anywhere
        found = [m for m in Config.MODES if re.search(rf"\b{re.escape(m)}\b", c)]
        if len(found) == 1:
            mode = found[0]
    if not mode:
        orch.speak(f"There are {len(Config.MODES)} modes: {_mode_speech()}. Which one would you like?")
        return True
    if mode in Config.MODES:
        previous = getattr(orch, "current_mode", None)
        if previous and previous != mode and hasattr(orch, "push_undo"):
            def _back(prev=previous):
                orch.current_mode = prev
                orch.send_to_ui("MODE", prev)
                return f"Back to {prev} mode."
            orch.push_undo("the mode change", _back)
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
    try:
        # os._exit below skips atexit and main()'s shutdown, so stop a dashboard bridge started by
        # "open web ui" here (otherwise it keeps running, orphaned, on ports 8765/8766)
        from interface.launcher import stop_bridge
        stop_bridge()
    except Exception as e:
        logging.debug("[handle_exit] bridge stop failed: %s: %s", type(e).__name__, e)
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


VOLUME_STEP = 10      # one "volume up/down" moves this many points (5 was too small to notice)


def handle_volume(orch, c, silent):
    """Volume up / down / set / mute / unmute. Reads the real value first and the real value back after,
    so what Flexie says is what Windows now has."""
    c = (c or "").lower()
    nums = get_numbers(c)
    curr = SystemCtrl.get_volume()
    if curr is None:
        orch.speak("I can't reach the Windows volume control right now, so I haven't changed anything.")
        return True
    muted = bool(SystemCtrl.get_mute())
    words = set(re.findall(r"[a-z']+", c))
    is_down = bool(words & {"down", "lower", "decrease", "quieter", "reduce", "drop", "softer"})
    is_up = bool(words & {"up", "raise", "increase", "louder", "higher", "boost"})
    big = bool(words & {"lot", "much", "way"})
    small = bool(words & {"little", "bit", "slightly", "touch"})
    step = 25 if big else 5 if small else VOLUME_STEP

    if "unmute" in words or "un-mute" in c:
        ok = SystemCtrl.set_mute(False)
        target = curr if curr > 0 else 30
        ok = ok and (target == curr or SystemCtrl.set_volume(target))
    elif "mute" in words:
        ok = SystemCtrl.set_mute(True)
        target = curr
    else:
        if nums:
            amt = nums[0]
            if "by" in words or ((is_down or is_up) and "to" not in words):
                target = curr - amt if is_down else curr + amt if is_up else amt
            else:
                target = amt
        elif "max" in words or "maximum" in words or "full" in words:
            target = 100
        elif "min" in words or "minimum" in words:
            target = 0
        elif is_up:
            target = curr + step
        elif is_down:
            target = curr - step
        else:
            target = 50
        target = max(0, min(100, int(target)))
        ok = SystemCtrl.set_volume(target)
        if ok and muted and target > 0:
            SystemCtrl.set_mute(False)               # moving the volume up should be heard
    if not ok:
        orch.speak("Windows didn't accept the volume change.")
        return True
    if hasattr(orch, "push_undo"):
        def _back(before=curr, was_muted=muted):
            SystemCtrl.set_volume(before)
            SystemCtrl.set_mute(was_muted)
            return f"Volume is back to {before} percent." if not was_muted else "Muted again."
        orch.push_undo("the volume change", _back)
    now = SystemCtrl.get_volume()
    is_muted = SystemCtrl.get_mute()
    if not silent:
        if is_muted:
            orch.speak("Muted.")
        elif "unmute" in words:
            orch.speak(f"Unmuted. Volume is {now if now is not None else target} percent.")
        else:
            orch.speak(f"Volume is {now if now is not None else target} percent.")
    return True


BRIGHTNESS_STEP = 15


def handle_brightness(orch, c, silent):
    """Brightness up / down / set. "increase brightness" used to set it to 70 whatever it was."""
    c = (c or "").lower()
    words = set(re.findall(r"[a-z']+", c))
    nums = get_numbers(c)
    curr = SystemCtrl.get_brightness()
    is_up = bool(words & {"up", "increase", "raise", "brighter", "brighten", "higher", "boost"})
    is_down = bool(words & {"down", "decrease", "lower", "dim", "dimmer", "darker", "reduce", "drop"})
    if curr is None and (is_up or is_down) and not nums:
        orch.speak("I can't read this screen's brightness, so I can't make it brighter or dimmer by a step. Say 'brightness 60' to set it.")
        return True
    step = 25 if words & {"lot", "much"} else 8 if words & {"little", "bit", "slightly"} else BRIGHTNESS_STEP
    if nums:
        amt = nums[0]
        target = (curr - amt if is_down else curr + amt) if (curr is not None and "by" in words) else amt
    elif is_up:
        target = curr + step
    elif is_down:
        target = curr - step
    elif words & {"max", "maximum", "full"}:
        target = 100
    elif words & {"min", "minimum"}:
        target = 5
    else:
        target = 70
    target = max(0, min(100, int(target)))
    SystemCtrl.set_brightness(target)
    if curr is not None and hasattr(orch, "push_undo"):
        def _back(before=curr):
            SystemCtrl.set_brightness(before)
            return f"Brightness is back to {before} percent."
        orch.push_undo("the brightness change", _back)
    if not silent:
        orch.speak(f"Brightness is {target} percent.")
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


_NUMBER_WORDS = {"one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3, "four": 4, "fourth": 4,
                 "five": 5, "fifth": 5, "six": 6, "sixth": 6}
_CANCEL_WORDS = ("cancel", "none", "nothing", "never mind", "nevermind", "no ", "stop", "leave it", "forget it")


def _pick_window(orch, target: str, windows: list):
    """Read the open windows back and wait for the user's choice.

    Returns ("one", window), ("all", None) or None (cancel, silence or unclear: close nothing).
    """
    shown = windows[:6]
    listing = "; ".join(f"{i + 1}: {w['title'][:48]}" for i, w in enumerate(shown))
    more = f", and {len(windows) - len(shown)} more" if len(windows) > len(shown) else ""
    orch.speak(f"I found {len(windows)} {target} windows. {listing}{more}. "
               "Which one should I close? Say a number, 'all', or 'cancel'.")
    try:
        ans = (orch.voice.listen(timeout=8) or "").strip().lower()
    except Exception:
        ans = ""
    if not ans or any(w in ans + " " for w in _CANCEL_WORDS):
        return None
    if re.search(r"\ball\b|\bevery\b|\beverything\b", ans):
        return ("all", None)
    m = re.search(r"\b(\d+)\b", ans)
    idx = int(m.group(1)) if m else next((n for w, n in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])) if re.search(rf"\b{w}\b", ans)), 0)
    if 1 <= idx <= len(shown):
        return ("one", shown[idx - 1])
    named = [w for w in shown if len(ans) >= 3 and ans in w["title"].lower()]
    return ("one", named[0]) if len(named) == 1 else None


def _close_target(orch, target: str, silent: bool) -> None:
    """Close an app. With several windows open, ask which one (never close them all unasked)."""
    windows = SystemCtrl.list_app_windows(target)
    if len(windows) >= 2:
        choice = _pick_window(orch, target, windows)
        if choice is None:
            if not silent:
                orch.speak("Okay, I didn't close anything.")
            return
        kind, win = choice
        if kind == "all":
            if orch.voice.confirm(f"Close all {len(windows)} {target} windows? Unsaved work may be lost."):
                SystemCtrl.close_app(target)
                if not silent:
                    orch.speak(f"Closed all {target} windows.")
            elif not silent:
                orch.speak("Okay, I left them open.")
            return
        sent = SystemCtrl.close_window(win["hwnd"])
        if not silent:
            orch.speak(f"Closing '{win['title'][:60]}'." if sent else "I couldn't close that window.")
        return
    if len(windows) == 1:
        # exactly one window: ask it to close politely so the app can still offer to save
        sent = SystemCtrl.close_window(windows[0]["hwnd"])
        if not silent:
            orch.speak(f"Closing {target}." if sent else f"I couldn't close {target}.")
        return
    closed = SystemCtrl.close_app(target)   # no visible window (background process): the old behaviour
    if not silent:
        orch.speak("I couldn't find a running app called " + target + "." if closed is False else f"Closed {target}.")


def handle_close_web_ui(orch, c):
    """"close the web ui / dashboard": stop the dashboard bridge (whoever started it)."""
    try:
        orch.send_to_ui("PANEL", "close")
    except Exception as _e:
        logging.debug("[close_web_ui] panel close failed: %s", _e)
    from interface.launcher import stop_any_bridge
    if stop_any_bridge():
        orch.speak("The web UI is closed. If its browser tab is still open, you can close it. "
                   "Say 'open web ui' to start it again.")
    else:
        orch.speak("The web UI isn't running.")
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
        _close_target(orch, target, silent)
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


WEB_UI_URL = "http://localhost:8766"


def _bridge_alive() -> bool:
    """True when the web bridge is listening (probe its WebSocket port, 8765)."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.5):
            return True
    except OSError:
        return False


def ensure_web_bridge(orch) -> bool:
    """Start the web bridge (dashboard + WebSocket) if it is not running; True when it is up."""
    from interface.launcher import bridge_alive, ensure_bridge  # one place starts, tracks and stops the bridge
    if _bridge_alive() and bridge_alive():
        return True
    orch.speak("Starting the web UI bridge.")
    return ensure_bridge()


def handle_open_web_ui(orch, c):
    """Open the web UI dashboard, auto-starting the bridge if it isn't running.

    Whatever you type (or speak) in the dashboard is relayed verbatim to the
    orchestrator and handled exactly like a normal command.
    """
    try:
        ensure_web_bridge(orch)
        webbrowser.open(WEB_UI_URL)
        orch.speak("Web UI opened. Type or speak anything in the dashboard and I will handle it.")
        return True
    except Exception as e:
        orch.speak(f"Failed to open web UI: {str(e)[:100]}")
        return True

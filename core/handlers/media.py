import re
import threading
import urllib.parse


def _wm(word: str, text: str) -> bool:
    """Word-boundary match — 'stop' won't hit 'stopwatch'."""
    return bool(re.search(r'\b' + re.escape(word) + r'\b', text))


def handle_play_youtube(orch, c):
    import threading

    if any(k in c for k in ["app", "build", "task", "project", "code"]):
        return False
    if any(_wm(x, c) for x in ["next", "skip", "kip"]):
        orch.speak("Skipping to the next track.")
        orch.speak(orch.yt.control_player("next"))
        return True

    clean_c = re.sub(r"^(play|search|open|start|watch|find)\s+", "", c).strip()
    clean_c = re.sub(r"\b(on youtube|on results|in youtube|from youtube|on yt)\b", "", clean_c).strip()
    clean_c = re.sub(r"\s+(on|it|now|for me)$", "", clean_c).strip()
    clean_c = re.sub(r"\b(the|a|some)\b", "", clean_c).strip()

    if not clean_c and orch.ctx.last_query:
        clean_c = orch.ctx.last_query

    if clean_c:
        orch.ctx.update(query=clean_c, engine="youtube", yt_query=clean_c)
        # Acknowledge immediately — don't block TTS on Playwright startup
        orch.speak(f"Playing {clean_c} on YouTube.")

        def _play_bg():
            try:
                result = orch.yt.play_video(clean_c)
                if result:
                    orch.speak(result)
                if hasattr(orch, "voice") and orch.voice:
                    orch.voice.suppress_asr = True
            except Exception as e:
                import logging
                logging.debug("YouTube play background error: %s", e)

        t = threading.Thread(target=_play_bg, daemon=True)
        t.start()
        t.join(timeout=0.05)
    else:
        orch.speak("What would you like me to play on YouTube?")
    return True


def handle_youtube(orch, c):
    if any(k in c for k in ["app", "build", "task", "project", "code", "folder", "directory", "download", "named", "file"]):
        return False
    if any(x in c for x in ["skip ad", "skip the ad", "skip the add", "kip ad", "kip the ad"]):
        orch.speak("Attempting to skip advertisement.")
        res = orch.yt.skip_ad()
        orch.speak(res)
        return True

    # "play next song" / "skip next" — must be caught before "play" maps to pause
    if any(_wm(x, c) for x in ["next", "skip"]):
        orch.speak(orch.yt.control_player("next"))
        return True

    # Advanced Controls — use word-boundary matching so "stopwatch" ≠ "stop"
    yt_actions = {
        "pause": ["pause video", "halt video", "resume video"],
        "fullscreen": ["fullscreen", "full screen", "maximize"],
        "theatre": ["theatre", "theater", "wide"],
        "captions": ["caption", "subtitle", "cc "],
        "speed up": ["fast", "speed up"],
        "slow down": ["slow"],
        "reset speed": ["normal speed", "reset speed"],
        "forward": ["forward", "ahead"],
        "backward": ["backward", "rewind", "go back"]
    }

    for act, triggers in yt_actions.items():
        if any(_wm(t, c) for t in triggers):
            # Re-enable mic on pause so user can still give commands
            if act == "pause" and hasattr(orch, "voice") and orch.voice:
                orch.voice.suppress_asr = False
            orch.speak(orch.yt.control_player(act))
            return True

    # Use same refined cleaning for search
    clean_c = re.sub(r"^(play|search|open|start|watch|find|show)\s+", "", c).strip()
    clean_c = re.sub(r"\b(on youtube|in youtube|on yt)\b", "", clean_c).strip()

    if not clean_c and orch.ctx.last_query:
        clean_c = orch.ctx.last_query

    is_explicit_yt = any(w in c for w in ["youtube", "yt"]) or any(c.startswith(p) for p in ["search ", "find ", "watch ", "look up "])
    if clean_c and is_explicit_yt:
        orch.ctx.update(query=clean_c, engine="youtube", yt_query=clean_c)
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean_c)}"
        orch.speak(f"Opening YouTube search for {clean_c}.")
        orch.browser.navigate(url)
        return True
    return False


def _parse_sleep_minutes(text):
    m = re.search(r"(\d+)\s*(min(?:ute)?s?|hrs?|hours?)", text)
    if m:
        v = int(m.group(1))
        if m.group(2).startswith("h"):
            return v * 60
        return v
    if "half an hour" in text or "half hour" in text:
        return 30
    if "one hour" in text:
        return 60
    return None


def handle_sleep_timer(orch, c):
    mins = _parse_sleep_minutes(c)
    if not mins:
        orch.speak("For how long? Say 'sleep timer for 30 minutes'.")
        return True
    def _stop():
        import time as _t
        _t.sleep(mins * 60)
        try:
            orch.music.stop()
        except Exception:
            pass
        try:
            orch.yt.control_player("pause")
        except Exception:
            pass
        orch.speak("Sleep timer ended. Playback stopped.")
    threading.Thread(target=_stop, daemon=True).start()
    orch.speak(f"Sleep timer set for {mins} minutes.")
    return True


def handle_media(orch, c):
    if any(k in c for k in ["app", "build", "task", "project", "code"]):
        return False
    if "sleep timer" in c or "sleep in" in c:
        return handle_sleep_timer(orch, c)

    # Persistence: If YouTube is active, prioritize it
    if orch.yt.is_session_active() or orch.ctx.active_engine == "youtube":
        if any(_wm(x, c) for x in ["stop", "pause", "halt", "resume", "play"]):
            orch.speak(orch.yt.control_player("pause" if any(_wm(x, c) for x in ["stop", "pause", "halt"]) else "play"))
        elif any(_wm(x, c) for x in ["next", "skip"]):
            orch.speak("Playing next on YouTube.")
            orch.speak(orch.yt.control_player("next"))
        return True

    if any(_wm(x, c) for x in ["stop", "pause", "halt"]):
        orch.music.stop()
        orch.speak("Playback stopped.")
    elif _wm("next", c):
        orch.music.next()
    return True

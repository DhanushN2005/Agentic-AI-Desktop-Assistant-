import re
import urllib.parse


def handle_play_youtube(orch, c):
    if any(x in c for x in ["next", "skip", "kip"]):
        orch.speak("Skipping to the next track.")
        orch.speak(orch.yt.control_player("next"))
        return True

    # Only strip the core command parts, keep the descriptive parts (like 'song')
    # 1. Strip common leading command starters
    clean_c = re.sub(r"^(play|search|open|start|watch|find)\s+", "", c).strip()
    # 2. Strip common YouTube connectors/targets
    clean_c = re.sub(r"\b(on youtube|on results|in youtube|from youtube|on yt)\b", "", clean_c).strip()
    # 3. Strip trailing fillers but keep middle ones
    clean_c = re.sub(r"\s+(on|it|now|for me)$", "", clean_c).strip()
    # 4. Final safety strip for specific triggers if they were at edges
    clean_c = re.sub(r"\b(the|a|some)\b", "", clean_c).strip()

    if not clean_c and orch.ctx.last_query:
        clean_c = orch.ctx.last_query

    if clean_c:
        orch.ctx.update(query=clean_c, engine="youtube", yt_query=clean_c)
        orch.speak(f"Playing {clean_c} on YouTube.")
        orch.speak(orch.yt.play_video(clean_c))
    else:
        orch.speak("What would you like me to play on YouTube?")
    return True


def handle_youtube(orch, c):
    if any(x in c for x in ["skip ad", "skip the ad", "skip the add", "kip ad", "kip the ad"]):
        orch.speak("Attempting to skip advertisement.")
        res = orch.yt.skip_ad()
        orch.speak(res)
        return True

    # Advanced Controls
    yt_actions = {
        "next": ["next", "skip song", "skip video"],
        "fullscreen": ["full screen", "fullscreen", "show full screen", "show fullscreen", "show in full screen"],
        "theatre": ["theatre mode", "theater mode", "wide mode"],
        "captions": ["caption", "subtitle"],
        "speed up": ["faster", "speed up", "increase speed"],
        "slow down": ["slower", "slow down", "decrease speed"],
        "reset speed": ["normal speed", "reset speed", "standard speed"],
        "forward": ["forward", "skip 10 seconds", "go ahead"],
        "backward": ["backward", "rewind", "go back 10 seconds"],
        "volume up": ["volume up", "increase volume", "louder"],
        "volume down": ["volume down", "decrease volume", "softer"]
    }

    for act, triggers in yt_actions.items():
        if any(t in c for t in triggers):
            orch.speak(orch.yt.control_player(act))
            return True

    # Use same refined cleaning for search
    clean_c = re.sub(r"^(play|search|open|start|watch|find|show)\s+", "", c).strip()
    clean_c = re.sub(r"\b(on youtube|in youtube|on yt)\b", "", clean_c).strip()

    if not clean_c and orch.ctx.last_query:
        clean_c = orch.ctx.last_query
    if clean_c:
        orch.ctx.update(query=clean_c, engine="youtube", yt_query=clean_c)
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(clean_c)}"
        orch.speak(f"Opening YouTube search for {clean_c}.")
        orch.browser.navigate(url)
    else:
        orch.speak("What should I look for on YouTube?")
    return True


def handle_media(orch, c):
    # Persistence: If YouTube is active, prioritize it
    if orch.yt.is_session_active() or orch.ctx.active_engine == "youtube":
        if any(x in c for x in ["stop", "pause", "halt", "resume", "play"]):
            orch.speak(orch.yt.control_player("pause" if any(x in c for x in ["stop", "pause", "halt"]) else "play"))
        elif any(x in c for x in ["next", "skip"]):
            orch.speak("Playing next on YouTube.")
            orch.speak(orch.yt.control_player("next"))
        return True

    if any(x in c for x in ["stop", "pause", "halt"]):
        orch.music.stop()
        orch.speak("Playback stopped.")
    elif "next" in c:
        orch.music.next()
    return True

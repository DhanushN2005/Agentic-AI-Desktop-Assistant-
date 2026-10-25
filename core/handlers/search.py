import re
import subprocess
import urllib.parse
import webbrowser
import logging


_BROWSER_NAMES = ("chrome", "edge", "firefox", "browser", "opera", "brave")

_IN_BROWSER_PATTERNS = [
    r"\bin\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\b",
    r"\bon\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\b",
    r"\busing\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\b",
    r"\bwith\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\b",
    r"\bbrowser automation\b",
    r"\busing playwright\b",
]


def _wants_browser_search(c: str, orch) -> bool:
    """True when the command explicitly targets an open browser or context shows one is active."""
    cl = c.lower()
    if any(re.search(p, cl) for p in _IN_BROWSER_PATTERNS):
        return True
    # Situation-aware: browser was opened earlier this session
    ctx = getattr(orch, "ctx", None)
    if ctx and getattr(ctx, "browser_open", False):
        return True
    return False


def handle_search(orch, c):
    cl = c.lower()

    # 1. Strip "in the opened chrome/browser/edge" phrasing from the raw command first
    clean_query = re.sub(
        r"\bin\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\s*",
        "", cl
    ).strip()
    clean_query = re.sub(
        r"\b(?:on|using|with)\s+(?:the\s+)?(?:open(?:ed)?\s+)?(?:chrome|edge|firefox|browser|opera|brave)\b",
        "", clean_query
    ).strip()

    # 2. Strip leading trigger words
    clean_query = re.sub(
        r"^(?:(?:search on chrome for|search on chrome|search for|search|google|look up|go to|find)\s+)+",
        "", clean_query
    ).strip()

    # 3. Also strip remaining trailing browser/platform words
    clean_query = re.sub(
        r"\b(in chrome|on chrome|with chrome|in browser|using browser|on edge|in edge)\b",
        "", clean_query
    ).strip()

    if not clean_query and any(b in cl for b in _BROWSER_NAMES):
        orch.speak("Opening your Google Chrome.")
        try:
            subprocess.Popen(['start', 'chrome', 'https://www.google.com'], shell=True)
        except Exception as _e:
            logging.debug("[core/handlers/search.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            webbrowser.open("https://www.google.com")
        return True

    if clean_query:
        orch.send_to_ui("STATE", "PROCESSING")
        use_browser = _wants_browser_search(c, orch)

        if use_browser and hasattr(orch, "browser") and orch.browser:
            # Situation-aware: search DIRECTLY in the open browser via Playwright
            try:
                orch.speak(f"Searching for '{clean_query}' in your open browser.")
                browser_res = orch.browser.search_in_browser(clean_query)
                orch.ctx.update(query=clean_query, last_search=clean_query)
                orch.send_to_ui("SAY", browser_res)
                return True
            except Exception as _be:
                logging.debug("BrowserEngine search failed, falling back: %s", _be)

        # Default: ask the brain for a knowledge answer
        summary = orch.brain.ask(f"Query: {clean_query}. Give a concise Answer/Summary for active user.")
        orch.ctx.update(query=clean_query, last_response=summary)
        orch.speak(summary)

        # Also open browser tab for deeper exploration
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(clean_query)}"
        try:
            subprocess.Popen(['start', 'chrome', url], shell=True)
        except Exception as _e:
            logging.debug("[core/handlers/search.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            webbrowser.open(url)
    else:
        orch.speak("What should I search for?")
    return True

import re
import subprocess
import urllib.parse
import webbrowser


def handle_search(orch, c):
    # 1. Clean query trigger words with absolute precision
    clean_query = re.sub(r"^(?:(?:search on chrome for|search on chrome|search for|search|google|look up|go to|find)\s+)+", "", c).strip()
    # 2. Extract specific search targets and remove browser names
    clean_query = re.sub(r"\b(in chrome|on chrome|with chrome|in browser|using browser|on edge|in edge)\b", "", clean_query).strip()

    if not clean_query and "chrome" in c:
        orch.speak("Opening your Google Chrome.")
        try:
            subprocess.Popen(['start', 'chrome', 'https://www.google.com'], shell=True)
        except Exception:
            webbrowser.open("https://www.google.com")
        return True

    if clean_query:
        orch.send_to_ui("STATE", "PROCESSING")
        summary = orch.brain.ask(f"Query: {clean_query}. Give a concise Answer/Summary for active user.")
        orch.ctx.update(query=clean_query, last_response=summary)
        orch.speak(summary)  # Re-speaking the summary

        # Open browser for deep research
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(clean_query)}"
        try:
            subprocess.Popen(['start', 'chrome', url], shell=True)
        except Exception:
            webbrowser.open(url)
    else:
        orch.speak("What should I search for?")
    return True

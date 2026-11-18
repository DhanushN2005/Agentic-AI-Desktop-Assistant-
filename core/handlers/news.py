from utils.config import Config
from utils.voice_parse import strip_wake


def handle_news(orch, c):
    """Handle news-related commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = strip_wake(c).lower()

    category = Config.DEFAULT_NEWS_CATEGORY
    if "tech" in cmd or "technology" in cmd:
        category = "tech"
    elif "science" in cmd:
        category = "science"
    elif "sport" in cmd:
        category = "sports"
    elif "world" in cmd or "international" in cmd:
        category = "world"
    elif "business" in cmd or "finance" in cmd or "economy" in cmd:
        category = "business"
    elif "entertainment" in cmd or "movie" in cmd or "music" in cmd:
        category = "entertainment"

    if any(w in cmd for w in ["summary", "summarize", "brief", "briefing"]):
        response = orch.news.get_summary(category, Config.DEFAULT_NEWS_SUMMARY)
    else:
        response = orch.news.get_headlines(category, Config.DEFAULT_NEWS_COUNT)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

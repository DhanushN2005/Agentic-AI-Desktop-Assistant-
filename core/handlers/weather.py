import re

from utils.config import Config
from utils.voice_parse import strip_wake

_TIME_WORDS = {
    "today", "tonight", "tomorrow", "now", "right", "this", "next", "the", "a", "an", "my",
    "week", "weekend", "weeks", "days", "day", "morning", "afternoon", "evening", "night",
    "forecast", "weather", "please", "outside", "here", "there", "it", "coming", "rest",
    "of", "and", "is", "be", "going", "will", "like", "currently", "later", "soon",
}
_CITY_RE = re.compile(
    r"\b(?:in|for|at|near|of)\s+"
    r"(?P<city>[^\W\d_][\w'\- ,]*?)"
    r"(?=\s+(?:today|tonight|tomorrow|now|right\s+now|this|next|please|forecast|weather|currently|"
    r"later|and|will|tomorrow)\b|\s*[?.!]|\s*$)",
    re.IGNORECASE,
)


def extract_city(original: str) -> str | None:
    """City named in the text (original case), or None when only filler follows
    the preposition ('forecast for this week')."""
    for m in _CITY_RE.finditer(original):
        city = re.sub(r"\s+", " ", m.group("city")).strip(" ,")
        words = [w for w in re.split(r"[\s,]+", city.lower()) if w]
        if not words or all(w in _TIME_WORDS for w in words) or words[0] in _TIME_WORDS:
            continue
        return city
    return None


def handle_weather(orch, c):
    """Handle weather-related commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()

    city = extract_city(original) or Config.DEFAULT_CITY

    if any(w in cmd for w in ["forecast", "week", "tomorrow", "coming days"]):
        response = orch.weather.get_forecast(city)
    else:
        response = orch.weather.get_current(city)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

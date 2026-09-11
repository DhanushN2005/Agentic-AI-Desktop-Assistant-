import re
from utils.config import Config


def handle_weather(orch, c):
    """Handle weather-related commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    city = Config.DEFAULT_CITY
    city_match = re.search(r"(?:in|for|at|of)\s+([a-zA-Z\s]+?)(?:\s+(?:today|tomorrow|this week|forecast)|\s*$)", cmd)
    if city_match:
        city = city_match.group(1).strip()

    if any(w in cmd for w in ["forecast", "week", "tomorrow", "coming days"]):
        response = orch.weather.get_forecast(city)
    else:
        response = orch.weather.get_current(city)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

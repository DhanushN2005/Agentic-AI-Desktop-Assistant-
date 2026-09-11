import json
import requests
from typing import Optional


class WeatherEngine:
    """Free weather engine using Open-Meteo API (no API key required)."""

    GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

    WMO_CODES = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        56: "Light freezing drizzle", 57: "Dense freezing drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        66: "Light freezing rain", 67: "Heavy freezing rain",
        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
        77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
        82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
    }

    def __init__(self):
        self._cache = {}

    def _geocode(self, city: str) -> Optional[dict]:
        if city in self._cache:
            return self._cache[city]
        try:
            resp = requests.get(self.GEO_URL, params={"name": city, "count": 1, "language": "en"}, timeout=5)
            data = resp.json()
            if "results" in data and data["results"]:
                loc = data["results"][0]
                result = {"lat": loc["latitude"], "lon": loc["longitude"], "name": loc.get("name", city)}
                self._cache[city] = result
                return result
        except Exception:
            pass
        return None

    def get_current(self, city: str = "Coimbatore") -> str:
        geo = self._geocode(city)
        if not geo:
            return f"Could not find location: {city}"
        try:
            resp = requests.get(self.WEATHER_URL, params={
                "latitude": geo["lat"], "longitude": geo["lon"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,apparent_temperature",
                "timezone": "auto"
            }, timeout=5)
            data = resp.json().get("current", {})
            temp = data.get("temperature_2m", "?")
            feels = data.get("apparent_temperature", "?")
            humidity = data.get("relative_humidity_2m", "?")
            wind = data.get("wind_speed_10m", "?")
            code = data.get("weather_code", 0)
            condition = self.WMO_CODES.get(code, "Unknown")
            return (
                f"Weather in {geo['name']}: {condition}, "
                f"{temp}°C (feels like {feels}°C), "
                f"humidity {humidity}%, wind {wind} km/h."
            )
        except Exception as e:
            return f"Weather service error: {e}"

    def get_forecast(self, city: str = "Coimbatore", days: int = 3) -> str:
        geo = self._geocode(city)
        if not geo:
            return f"Could not find location: {city}"
        try:
            resp = requests.get(self.WEATHER_URL, params={
                "latitude": geo["lat"], "longitude": geo["lon"],
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "auto", "forecast_days": days
            }, timeout=5)
            data = resp.json().get("daily", {})
            dates = data.get("time", [])
            maxtemps = data.get("temperature_2m_max", [])
            mintemps = data.get("temperature_2m_min", [])
            codes = data.get("weather_code", [])
            lines = []
            for i in range(min(len(dates), days)):
                cond = self.WMO_CODES.get(codes[i], "Unknown")
                lines.append(f"{dates[i]}: {cond}, {mintemps[i]}°C to {maxtemps[i]}°C")
            return f"Forecast for {geo['name']}: " + "; ".join(lines) + "."
        except Exception as e:
            return f"Forecast error: {e}"

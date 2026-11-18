import logging
import time

import requests

_SESSION = None


class WeatherServiceError(Exception):
    """The weather/geocoding service failed (network, HTTP status or bad JSON)."""


def _get_session():
    """One shared HTTP session (connection reuse) for the weather engine."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": "Flexie/2.0"})
    return _SESSION


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

    GEO_TTL = None          # geocode results never expire
    WEATHER_TTL = 600.0     # seconds (~10 minutes)

    def __init__(self, clock=None):
        self._cache = {}            # geocode: city.lower() -> geo dict (kept forever)
        self._wx_cache = {}         # (kind, lat, lon, days) -> (stamp, text)
        self._clock = clock or time.monotonic
        self._session = _get_session()

    # ---------------------------------------------------------------- helpers
    def _get_json(self, url: str, params: dict) -> dict:
        """GET + status/JSON validation.  Raises WeatherServiceError."""
        try:
            resp = self._session.get(url, params=params, timeout=5)
        except Exception as e:
            logging.debug("[engines/weather.py] request failed: %s: %s", type(e).__name__, e)
            raise WeatherServiceError(str(e)) from e
        if resp.status_code != 200:
            raise WeatherServiceError(f"HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as e:
            raise WeatherServiceError("invalid response") from e
        if not isinstance(data, dict) or data.get("error"):
            raise WeatherServiceError("service reported an error")
        return data

    def _geocode(self, city: str) -> dict | None:
        """Location dict, None if the place does not exist.
        Raises WeatherServiceError when the geocoder itself is unavailable."""
        key = " ".join(city.lower().split())
        if key in self._cache:
            return self._cache[key]
        name, _, extra = city.partition(",")
        name = name.strip() or city.strip()
        extra = extra.strip().lower()
        data = self._get_json(self.GEO_URL, {"name": name, "count": 10 if extra else 1, "language": "en"})
        results = data.get("results") or []
        if not results:
            return None
        loc = results[0]
        if extra:
            for cand in results:
                hay = " ".join(str(cand.get(k, "")).lower() for k in ("admin1", "admin2", "country", "country_code"))
                if extra in hay:
                    loc = cand
                    break
        if "latitude" not in loc or "longitude" not in loc:
            raise WeatherServiceError("incomplete geocoding data")
        result = {"lat": loc["latitude"], "lon": loc["longitude"], "name": loc.get("name", name)}
        self._cache[key] = result
        return result

    def _cached(self, key):
        hit = self._wx_cache.get(key)
        if hit and self._clock() - hit[0] < self.WEATHER_TTL:
            return hit[1]
        return None

    def _store(self, key, text):
        self._wx_cache[key] = (self._clock(), text)
        return text

    def _locate(self, city: str):
        """(geo, error_message)"""
        try:
            geo = self._geocode(city)
        except WeatherServiceError:
            return None, "The weather service is unavailable right now. Please try again later."
        if not geo:
            return None, f"Could not find location: {city}"
        return geo, None

    # ------------------------------------------------------------------- API
    def get_current(self, city: str = "Coimbatore") -> str:
        geo, err = self._locate(city)
        if err:
            return err
        key = ("current", geo["lat"], geo["lon"], 0)
        hit = self._cached(key)
        if hit:
            return hit
        try:
            data = self._get_json(self.WEATHER_URL, {
                "latitude": geo["lat"], "longitude": geo["lon"],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code,apparent_temperature",
                "timezone": "auto"
            }).get("current")
            if not isinstance(data, dict) or data.get("temperature_2m") is None:
                raise WeatherServiceError("no current conditions")
        except WeatherServiceError as e:
            logging.debug("[engines/weather.py] current failed: %s", e)
            return "The weather service is unavailable right now. Please try again later."
        temp = data.get("temperature_2m")
        feels = data.get("apparent_temperature", "?")
        humidity = data.get("relative_humidity_2m", "?")
        wind = data.get("wind_speed_10m", "?")
        code = data.get("weather_code")
        condition = self.WMO_CODES.get(code, "Unknown conditions")
        return self._store(key, (
            f"Weather in {geo['name']}: {condition}, "
            f"{temp}°C (feels like {feels}°C), "
            f"humidity {humidity}%, wind {wind} km/h."
        ))

    def get_forecast(self, city: str = "Coimbatore", days: int = 3) -> str:
        days = max(1, min(int(days), 16))
        geo, err = self._locate(city)
        if err:
            return err
        key = ("forecast", geo["lat"], geo["lon"], days)
        hit = self._cached(key)
        if hit:
            return hit
        try:
            data = self._get_json(self.WEATHER_URL, {
                "latitude": geo["lat"], "longitude": geo["lon"],
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "auto", "forecast_days": days
            }).get("daily")
            if not isinstance(data, dict):
                raise WeatherServiceError("no forecast")
            dates = data.get("time") or []
            maxtemps = data.get("temperature_2m_max") or []
            mintemps = data.get("temperature_2m_min") or []
            codes = data.get("weather_code") or []
            n = min(len(dates), len(maxtemps), len(mintemps), len(codes), days)
            if n == 0:
                raise WeatherServiceError("empty forecast")
        except WeatherServiceError as e:
            logging.debug("[engines/weather.py] forecast failed: %s", e)
            return "The weather service is unavailable right now. Please try again later."
        lines = []
        for i in range(n):
            cond = self.WMO_CODES.get(codes[i], "Unknown conditions")
            lines.append(f"{dates[i]}: {cond}, {mintemps[i]}°C to {maxtemps[i]}°C")
        return self._store(key, f"Forecast for {geo['name']}: " + "; ".join(lines) + ".")

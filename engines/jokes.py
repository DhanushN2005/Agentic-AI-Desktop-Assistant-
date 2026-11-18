import json
import logging
import urllib.parse
import urllib.request

_NO_JOKE = "Couldn't fetch a joke right now. Try again later."


def _format(data) -> str | None:
    """Turn a JokeAPI/icanhazdadjoke payload into text, or None when unusable."""
    if not isinstance(data, dict):
        return None
    if data.get("error") is True:
        return None
    if data.get("type") == "twopart":
        setup, delivery = data.get("setup"), data.get("delivery")
        if setup and delivery:
            return f"{setup}\n{delivery}"
        return None
    joke = data.get("joke")
    return str(joke) if joke else None


class JokesEngine:
    """Free jokes from multiple APIs — no API key needed."""

    def _get_json(self, url: str, headers: dict | None = None):
        h = {"User-Agent": "Flexie/2.0"}
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise OSError(f"HTTP {status}")
            return json.loads(resp.read().decode())

    def get_joke(self, category: str = "general") -> str:
        try:
            text = _format(self._get_json("https://icanhazdadjoke.com/", {"Accept": "application/json"}))
            if text:
                return text
        except Exception as _e:
            logging.debug("[engines/jokes.py] %s: %s", type(_e).__name__, _e)

        try:
            text = _format(self._get_json("https://v2.jokeapi.dev/joke/Any?safe-mode"))
            if text:
                return text
        except Exception as _e:
            logging.debug("[engines/jokes.py] %s: %s", type(_e).__name__, _e)
        return _NO_JOKE

    def get_category(self, category: str) -> str:
        cat = (category or "").strip()
        if cat.lower() == "dark":
            return ("Dark jokes are turned off because safe mode is on. "
                    "Here is a regular one instead: " + self.get_joke())
        try:
            url = f"https://v2.jokeapi.dev/joke/{urllib.parse.quote(cat, safe='')}?safe-mode"
            text = _format(self._get_json(url))
            if text:
                return text
        except Exception as _e:
            logging.debug("[engines/jokes.py] %s: %s", type(_e).__name__, _e)
        return self.get_joke()

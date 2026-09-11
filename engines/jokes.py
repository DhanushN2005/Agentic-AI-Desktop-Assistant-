import urllib.request
import json


class JokesEngine:
    """Free jokes from multiple APIs — no API key needed."""

    def get_joke(self, category: str = "general") -> str:
        # Try icanhazdadjoke first
        try:
            req = urllib.request.Request(
                "https://icanhazdadjoke.com/",
                headers={"User-Agent": "Flexie/2.0", "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("joke", "No joke found.")
        except Exception:
            pass

        # Try JokeAPI
        try:
            url = f"https://v2.jokeapi.dev/joke/Any?safe-mode"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("type") == "single":
                    return data.get("joke", "No joke found.")
                elif data.get("type") == "twopart":
                    return f"{data.get('setup', '')}\n{data.get('delivery', '')}"
        except Exception:
            pass

        return "Couldn't fetch a joke right now. Try again later."

    def get_category(self, category: str) -> str:
        try:
            url = f"https://v2.jokeapi.dev/joke/{urllib.parse.quote(category)}?safe-mode"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("type") == "single":
                    return data.get("joke", "No joke found.")
                elif data.get("type") == "twopart":
                    return f"{data.get('setup', '')}\n{data.get('delivery', '')}"
        except Exception:
            return self.get_joke()

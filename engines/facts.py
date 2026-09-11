import urllib.request
import json


class FactsEngine:
    """Free random facts — no API key needed."""

    def get_random(self) -> str:
        # Try uselessfacts API
        try:
            req = urllib.request.Request(
                "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en",
                headers={"User-Agent": "Flexie/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                text = data.get("text", "")
                if text:
                    return f"Fun fact: {text}"
        except Exception:
            pass

        # Try new API
        try:
            req = urllib.request.Request(
                "https://api.api-ninjas.com/v1/fact",
                headers={"User-Agent": "Flexie/2.0", "X-Api-Key": "demo"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                fact = data.get("fact", "")
                if fact:
                    return f"Fun fact: {fact}"
        except Exception:
            pass

        return "Couldn't fetch a fact right now."

    def get_by_category(self, category: str) -> str:
        try:
            url = f"https://uselessfacts.jsph.pl/api/v2/facts/random?language=en"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                text = data.get("text", "")
                if text:
                    return f"Fact about {category}: {text}"
        except Exception:
            pass
        return self.get_random()

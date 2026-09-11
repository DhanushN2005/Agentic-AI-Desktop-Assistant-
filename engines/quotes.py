import urllib.request
import json


class QuotesEngine:
    """Free motivational quotes — no API key needed."""

    def get_random(self) -> str:
        # Try zenquotes
        try:
            req = urllib.request.Request(
                "https://zenquotes.io/api/random",
                headers={"User-Agent": "Flexie/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data and len(data) > 0:
                    q = data[0]
                    return f'"{q.get("q", "")}" — {q.get("a", "Unknown")}'
        except Exception:
            pass

        # Tryquotable
        try:
            req = urllib.request.Request(
                "https://api.quotable.io/random",
                headers={"User-Agent": "Flexie/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return f'"{data.get("content", "")}" — {data.get("author", "Unknown")}'
        except Exception:
            pass

        return "Couldn't fetch a quote right now."

    def get_by_author(self, author: str) -> str:
        try:
            url = f"https://api.quotable.io/quotes?author={author.replace(' ', '-')}&limit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                results = data.get("results", [])
                if results:
                    q = results[0]
                    return f'"{q.get("content", "")}" — {q.get("author", "Unknown")}'
        except Exception:
            pass
        return self.get_random()

    def get_by_tag(self, tag: str) -> str:
        try:
            url = f"https://api.quotable.io/quotes?tags={tag.replace(' ', '-')}&limit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                results = data.get("results", [])
                if results:
                    q = results[0]
                    return f'"{q.get("content", "")}" — {q.get("author", "Unknown")}'
        except Exception:
            pass
        return self.get_random()

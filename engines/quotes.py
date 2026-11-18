import json
import logging
import random
import urllib.request

# api.quotable.io is defunct, so the author/tag lookups use this bundled list.
BUNDLED_QUOTES = [
    ("The only way to do great work is to love what you do.", "Steve Jobs", ["motivational", "success", "life"]),
    ("It always seems impossible until it is done.", "Nelson Mandela", ["motivational", "inspirational"]),
    ("The journey of a thousand miles begins with a single step.", "Lao Tzu", ["wisdom", "inspirational"]),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein", ["wisdom", "motivational"]),
    ("Whether you think you can or you think you can't, you're right.", "Henry Ford", ["success", "motivational"]),
    ("The unexamined life is not worth living.", "Socrates", ["wisdom", "life"]),
    ("Life is what happens when you're busy making other plans.", "John Lennon", ["life"]),
    ("Being deeply loved by someone gives you strength; loving someone deeply gives you courage.", "Lao Tzu", ["love"]),
    ("A day without laughter is a day wasted.", "Charlie Chaplin", ["humor", "life"]),
    ("Success is not final, failure is not fatal: it is the courage to continue that counts.", "Winston Churchill", ["success", "inspirational"]),
    ("Do what you can, with what you have, where you are.", "Theodore Roosevelt", ["motivational", "wisdom"]),
    ("Imagination is more important than knowledge.", "Albert Einstein", ["inspirational", "wisdom"]),
]


def _fmt(text, author) -> str:
    return f'"{text}" — {author or "Unknown"}'


def _pick(items):
    q = random.choice(items)
    return _fmt(q[0], q[1])


class QuotesEngine:
    """Motivational quotes: zenquotes.io live, bundled list as fallback."""

    def get_random(self) -> str:
        try:
            req = urllib.request.Request(
                "https://zenquotes.io/api/random", headers={"User-Agent": "Flexie/2.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise OSError(f"HTTP {status}")
                data = json.loads(resp.read().decode())
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    q = data[0]
                    if q.get("q"):
                        return _fmt(q["q"], q.get("a"))
        except Exception as _e:
            logging.debug("[engines/quotes.py] %s: %s", type(_e).__name__, _e)
        return _pick(BUNDLED_QUOTES)

    def get_by_author(self, author: str) -> str:
        key = (author or "").strip().lower()
        matches = [q for q in BUNDLED_QUOTES if key and key in q[1].lower()]
        if matches:
            return _pick(matches)
        return f"I don't have a quote by {author.strip() if author else 'that author'}. Here's another one: " + self.get_random()

    def get_by_tag(self, tag: str) -> str:
        key = (tag or "").strip().lower()
        matches = [q for q in BUNDLED_QUOTES if key in q[2]]
        if matches:
            return _pick(matches)
        return self.get_random()

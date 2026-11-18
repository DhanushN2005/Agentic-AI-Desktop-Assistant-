import logging
import time
import xml.etree.ElementTree as ET

import requests

_SESSION = None


def _get_session():
    """One shared HTTP session (connection reuse) for the news engine."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({"User-Agent": "Flexie/2.0"})
    return _SESSION


class NewsEngine:
    """Free news aggregator using RSS feeds (no API key required)."""

    FEEDS = {
        "general": "https://feeds.bbci.co.uk/news/rss.xml",
        "tech": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "sports": "https://feeds.bbci.co.uk/sport/rss.xml",
        "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "business": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "entertainment": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    }

    CACHE_TTL = 600.0   # seconds (~10 minutes)
    MAX_ITEMS = 20

    def __init__(self, clock=None):
        self._cache = {}    # category -> (stamp, items)
        self._clock = clock or time.monotonic
        self._session = _get_session()

    def _load(self, category: str):
        """Feed items (cached ~10 min).  None = the fetch failed (never cached)."""
        hit = self._cache.get(category)
        if hit and self._clock() - hit[0] < self.CACHE_TTL:
            return hit[1]
        url = self.FEEDS.get(category, self.FEEDS["general"])
        try:
            resp = self._session.get(url, timeout=10)
            if resp.status_code != 200:
                logging.debug("[engines/news.py] feed HTTP %s", resp.status_code)
                return None
            root = ET.fromstring(resp.content)
            items = []
            for item in root.findall(".//item"):
                title = item.find("title")
                text = (title.text or "").strip() if title is not None else ""
                if not text:
                    continue   # skip items with a missing/None title
                desc = item.find("description")
                link = item.find("link")
                items.append({
                    "title": text,
                    "description": (desc.text or "").strip() if desc is not None else "",
                    "link": (link.text or "").strip() if link is not None else "",
                })
                if len(items) >= self.MAX_ITEMS:
                    break
        except Exception as _e:
            logging.debug("[engines/news.py] feed failed: %s: %s", type(_e).__name__, _e)
            return None
        self._cache[category] = (self._clock(), items)
        return items

    def _fetch_feed(self, category: str = "general", limit: int = 5) -> list[dict]:
        items = self._load(category)
        return (items or [])[:max(int(limit), 0)]

    def get_headlines(self, category: str = "general", limit: int = 5) -> str:
        items = self._load(category)
        if items is None:
            return "I couldn't reach the news service right now. Please try again in a few minutes."
        items = items[:max(int(limit), 1)]
        if not items:
            return f"No {category} news available right now."
        lines = [f"{i+1}. {item['title']}" for i, item in enumerate(items)]
        return f"Top {category} headlines: " + "; ".join(lines) + "."

    def get_summary(self, category: str = "general", limit: int = 3) -> str:
        items = self._load(category)
        if items is None:
            return "I couldn't reach the news service right now. Please try again in a few minutes."
        items = items[:max(int(limit), 1)]
        if not items:
            return f"No {category} news available."
        lines = []
        for i, item in enumerate(items):
            desc = item["description"][:100] + "..." if len(item["description"]) > 100 else item["description"]
            lines.append(f"{i+1}. {item['title']}. {desc}")
        return "News summary: " + " ".join(lines)

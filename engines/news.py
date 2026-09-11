import requests
import re
import xml.etree.ElementTree as ET
from typing import List, Dict


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

    def __init__(self):
        self._cache = {}

    def _fetch_feed(self, category: str = "general", limit: int = 5) -> List[Dict]:
        url = self.FEEDS.get(category, self.FEEDS["general"])
        try:
            resp = requests.get(url, timeout=10)
            root = ET.fromstring(resp.content)
            items = []
            for item in root.findall(".//item")[:limit]:
                title = item.find("title")
                desc = item.find("description")
                link = item.find("link")
                items.append({
                    "title": title.text if title is not None else "No title",
                    "description": desc.text.strip() if desc is not None and desc.text else "",
                    "link": link.text if link is not None else "",
                })
            return items
        except Exception:
            return []

    def get_headlines(self, category: str = "general", limit: int = 5) -> str:
        items = self._fetch_feed(category, limit)
        if not items:
            return f"No {category} news available right now."
        lines = [f"{i+1}. {item['title']}" for i, item in enumerate(items)]
        return f"Top {category} headlines: " + "; ".join(lines) + "."

    def get_summary(self, category: str = "general", limit: int = 3) -> str:
        items = self._fetch_feed(category, limit)
        if not items:
            return f"No {category} news available."
        lines = []
        for i, item in enumerate(items):
            desc = item["description"][:100] + "..." if len(item["description"]) > 100 else item["description"]
            lines.append(f"{i+1}. {item['title']}. {desc}")
        return f"News summary: " + " ".join(lines)

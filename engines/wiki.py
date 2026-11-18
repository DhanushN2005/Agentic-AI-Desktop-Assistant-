import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
_SEARCH = "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&format=json&srlimit=1"


def _first_sentences(text: str, n: int) -> str:
    """First n sentences of text (n >= 1)."""
    n = max(int(n), 1)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text.strip())
    return " ".join(parts[:n])


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


class WikiEngine:
    """Free Wikipedia search - no API key needed."""

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search(self, query: str, sentences: int = 3) -> str:
        quoted = urllib.parse.quote(query.strip(), safe="")
        try:
            data = self._get(_SUMMARY + quoted)
            if data.get("type") != "disambiguation" and data.get("extract"):
                title = data.get("title", query)
                extract = _first_sentences(data["extract"], sentences)
                page_url = (data.get("content_urls") or {}).get("desktop", {}).get("page", "")
                result = f"{title}: {extract}"
                if page_url:
                    result += f"\nRead more: {page_url}"
                return result
        except urllib.error.HTTPError as _e:
            logging.debug("[engines/wiki.py] summary HTTP %s", _e.code)
        except Exception as _e:
            logging.debug("[engines/wiki.py] summary failed: %s: %s", type(_e).__name__, _e)

        # Search fallback
        try:
            data = self._get(_SEARCH.format(q=quoted))
            results = (data.get("query") or {}).get("search") or []
            if results:
                snippet = _strip_html(results[0].get("snippet", ""))
                return f"Found: {results[0]['title']} - {snippet}" if snippet else f"Found: {results[0]['title']}"
            return f"No Wikipedia article found for '{query}'."
        except Exception as _e:
            logging.debug("[engines/wiki.py] search failed: %s: %s", type(_e).__name__, _e)
            return f"Could not search Wikipedia for '{query}'."

    def get_page(self, title: str) -> str:
        try:
            data = self._get(_SUMMARY + urllib.parse.quote(title.strip(), safe=""))
            return data.get("extract") or "No content found."
        except Exception as _e:
            logging.debug("[engines/wiki.py] get_page failed: %s: %s", type(_e).__name__, _e)
            return f"Could not fetch Wikipedia page for '{title}'."

import urllib.request
import json


class WikiEngine:
    """Free Wikipedia search — no API key needed."""

    def search(self, query: str, sentences: int = 3) -> str:
        try:
            search_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query)}"
            req = urllib.request.Request(search_url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                title = data.get("title", query)
                extract = data.get("extract", "No summary found.")
                page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                result = f"{title}: {extract}"
                if page_url:
                    result += f"\nRead more: {page_url}"
                return result
        except Exception as e:
            # Try search fallback
            try:
                search_api = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json&srlimit=1"
                req = urllib.request.Request(search_api, headers={"User-Agent": "Flexie/2.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    results = data.get("query", {}).get("search", [])
                    if results:
                        return f"Found: {results[0]['title']} — {results[0].get('snippet', '')}"
                    return f"No Wikipedia article found for '{query}'."
            except Exception:
                return f"Could not search Wikipedia for '{query}'."

    def get_page(self, title: str) -> str:
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                extract = data.get("extract", "No content found.")
                return extract
        except Exception as e:
            return f"Could not fetch Wikipedia page for '{title}'."

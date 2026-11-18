import html
import logging
import re

import requests


class TextSummarizerEngine:
    """Local text summarizer using extractive summarization (no API key required)."""

    def __init__(self):
        pass

    def summarize(self, text: str, num_sentences: int = 3) -> str:
        """Extractive summarization: pick most important sentences."""
        if not text or len(text.strip()) < 50:
            return text

        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        if len(sentences) <= num_sentences:
            return text

        # Score sentences by position + word frequency
        word_freq = {}
        for word in re.findall(r'\b\w+\b', text.lower()):
            if len(word) > 3:
                word_freq[word] = word_freq.get(word, 0) + 1

        scored = []
        for i, sent in enumerate(sentences):
            words = re.findall(r'\b\w+\b', sent.lower())
            score = sum(word_freq.get(w, 0) for w in words)
            # Boost first and last sentences
            if i == 0:
                score *= 1.5
            elif i == len(sentences) - 1:
                score *= 1.2
            scored.append((score, i, sent))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = sorted(scored[:num_sentences], key=lambda x: x[1])
        return " ".join(s[2] for s in top)

    @staticmethod
    def html_to_text(raw: str) -> str:
        """Visible text of an HTML page: <script>/<style>/comments removed."""
        raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
        raw = re.sub(r"(?is)<(script|style|noscript|template|svg)\b.*?</\1\s*>", " ", raw)
        text = re.sub(r"(?s)<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", html.unescape(text)).strip()

    def summarize_url(self, url: str, num_sentences: int = 3) -> str:
        """Fetch URL content and summarize it."""
        if not re.match(r"https?://", url or "", re.IGNORECASE):
            return "Please give me a full http or https link to summarize."
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return f"Couldn't fetch that page (HTTP {resp.status_code})."
            ctype = (resp.headers.get("Content-Type") or "").lower()
            body = resp.text[:2_000_000]
            text = self.html_to_text(body) if ("html" in ctype or not ctype or "<" in body[:200]) else re.sub(r"\s+", " ", body).strip()
            if not text:
                return "That page has no readable text to summarize."
            if len(text) > 5000:
                text = text[:5000]
            return self.summarize(text, num_sentences)
        except Exception as e:
            logging.debug("[engines/text_summarizer.py] fetch failed: %s: %s", type(e).__name__, e)
            return f"Error fetching content: {e}"

    def summarize_file(self, filepath: str, num_sentences: int = 5) -> str:
        """Read a text file and summarize it."""
        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                text = f.read(2_000_000)
            return self.summarize(text, num_sentences)
        except Exception as e:
            logging.debug("[engines/text_summarizer.py] read failed: %s: %s", type(e).__name__, e)
            return f"Error reading file: {e}"

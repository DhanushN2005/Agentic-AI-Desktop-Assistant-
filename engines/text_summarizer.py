import re
import requests
from typing import Optional


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

    def summarize_url(self, url: str, num_sentences: int = 3) -> str:
        """Fetch URL content and summarize it."""
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            text = re.sub(r'<[^>]+>', ' ', resp.text)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 5000:
                text = text[:5000]
            return self.summarize(text, num_sentences)
        except Exception as e:
            return f"Error fetching content: {e}"

    def summarize_file(self, filepath: str, num_sentences: int = 5) -> str:
        """Read a text file and summarize it."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            return self.summarize(text, num_sentences)
        except Exception as e:
            return f"Error reading file: {e}"

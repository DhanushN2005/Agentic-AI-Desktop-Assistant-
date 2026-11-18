import json
import logging
import urllib.error
import urllib.parse
import urllib.request

_BASE = "https://api.dictionaryapi.dev/api/v2/entries/en/"


class DictionaryEngine:
    """Free dictionary definitions - no API key needed."""

    def _fetch(self, word: str):
        """Entries list.  Returns (entries, status) with status in
        'ok' | 'notfound' | 'error'."""
        url = _BASE + urllib.parse.quote(word.strip(), safe="")
        req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logging.debug("[engines/dictionary.py] HTTP %s for %r", e.code, word)
            return None, ("notfound" if e.code == 404 else "error")
        except Exception as e:
            logging.debug("[engines/dictionary.py] lookup failed: %s: %s", type(e).__name__, e)
            return None, "error"
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None, "notfound"
        return data, "ok"

    def define(self, word: str) -> str:
        entries, status = self._fetch(word)
        if status == "error":
            return f"Could not look up '{word}'."
        if status == "notfound":
            return f"No definition found for '{word}'."
        entry = entries[0]
        word_text = entry.get("word", word)
        phonetic = entry.get("phonetic", "")
        results = []
        for meaning in entry.get("meanings", []):
            pos = meaning.get("partOfSpeech", "")
            for defn in meaning.get("definitions", [])[:2]:
                definition = defn.get("definition", "")
                example = defn.get("example", "")
                line = f"[{pos}] {definition}"
                if example:
                    line += f' (e.g. "{example}")'
                results.append(line)
        phonetic_str = f" ({phonetic})" if phonetic else ""
        return f"{word_text}{phonetic_str}\n" + "\n".join(results[:4])

    def _related(self, word: str, field: str, label: str) -> str:
        entries, status = self._fetch(word)
        if status == "error":
            return f"Could not look up {label} for '{word}'."
        if status == "notfound":
            return f"No {label} found for '{word}'."
        found = []  # first-seen order -> deterministic output
        for meaning in entries[0].get("meanings", []):
            found.extend(meaning.get(field, []) or [])
            for defn in meaning.get("definitions", []):
                found.extend(defn.get(field, []) or [])
        found = list(dict.fromkeys(found))
        if found:
            return f"{label.capitalize()} for '{word}': {', '.join(found[:10])}"
        return f"No {label} found for '{word}'."

    def synonyms(self, word: str) -> str:
        return self._related(word, "synonyms", "synonyms")

    def antonyms(self, word: str) -> str:
        return self._related(word, "antonyms", "antonyms")

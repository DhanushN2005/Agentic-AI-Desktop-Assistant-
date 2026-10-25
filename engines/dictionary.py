import json
import urllib.request
import logging


class DictionaryEngine:
    """Free dictionary definitions — no API key needed."""

    def define(self, word: str) -> str:
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if not data:
                    return f"No definition found for '{word}'."

                entry = data[0]
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
                output = f"{word_text}{phonetic_str}\n" + "\n".join(results[:4])
                return output
        except urllib.error.HTTPError as _e:
            logging.debug("[engines/dictionary.py:35] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"No definition found for '{word}'."
        except Exception as _e:
            logging.debug("[engines/dictionary.py:37] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Could not look up '{word}'."

    def synonyms(self, word: str) -> str:
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if not data:
                    return f"No synonyms found for '{word}'."

                synonyms = set()
                for meaning in data[0].get("meanings", []):
                    for defn in meaning.get("definitions", []):
                        for s in defn.get("synonyms", []):
                            synonyms.add(s)

                if synonyms:
                    return f"Synonyms for '{word}': {', '.join(list(synonyms)[:10])}"
                return f"No synonyms found for '{word}'."
        except Exception as _e:
            logging.debug("[engines/dictionary.py:58] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Could not look up synonyms for '{word}'."

    def antonyms(self, word: str) -> str:
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if not data:
                    return f"No antonyms found for '{word}'."

                antonyms = set()
                for meaning in data[0].get("meanings", []):
                    for defn in meaning.get("definitions", []):
                        for a in defn.get("antonyms", []):
                            antonyms.add(a)

                if antonyms:
                    return f"Antonyms for '{word}': {', '.join(list(antonyms)[:10])}"
                return f"No antonyms found for '{word}'."
        except Exception as _e:
            logging.debug("[engines/dictionary.py:79] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Could not look up antonyms for '{word}'."

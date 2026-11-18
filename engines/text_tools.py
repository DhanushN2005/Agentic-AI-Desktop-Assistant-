import re


class TextToolsEngine:
    """Text manipulation tools — no API needed."""

    def word_count(self, text: str) -> str:
        words = text.split()
        chars = len(text)
        chars_no_space = len(re.sub(r"\s+", "", text))
        lines = len(text.splitlines()) if text else 0
        sentences = len([p for p in re.split(r"[.!?]+", text) if p.strip()])
        return f"Words: {len(words)}, Characters: {chars}, Characters (no spaces): {chars_no_space}, Lines: {lines}, Sentences: {sentences}"

    def char_count(self, text: str) -> str:
        return f"Characters: {len(text)}"

    def reverse(self, text: str) -> str:
        return text[::-1]

    def uppercase(self, text: str) -> str:
        return text.upper()

    def lowercase(self, text: str) -> str:
        return text.lower()

    def title_case(self, text: str) -> str:
        # str.title() capitalises after apostrophes ("Don'T"); do it per word instead.
        return re.sub(r"[^\W\d_]+(?:['’][^\W\d_]+)*",
                      lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text)

    def sentence_case(self, text: str) -> str:
        if not text:
            return text
        if text.isupper():
            text = text.lower()
        return re.sub(r"(^\s*|[.!?]\s+)([^\W\d_])",
                      lambda m: m.group(1) + m.group(2).upper(), text)

    def snake_case(self, text: str) -> str:
        text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        return '_'.join(text.split()).lower()

    def camel_case(self, text: str) -> str:
        words = re.sub(r'[^a-zA-Z0-9\s]', '', text).split()
        if not words:
            return ""
        return words[0].lower() + ''.join(w.capitalize() for w in words[1:])

    def kebab_case(self, text: str) -> str:
        text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        return '-'.join(text.split()).lower()

    def remove_duplicates(self, text: str) -> str:
        seen = set()
        out = []
        for line in text.split(chr(10)):
            if line not in seen:
                seen.add(line)
                out.append(line)
        return chr(10).join(out)

    def sort_lines(self, text: str, reverse: bool = False) -> str:
        lines = text.split("\n")
        lines.sort(reverse=reverse)
        return "\n".join(lines)

    def find_replace(self, text: str, find: str, replace: str) -> str:
        return text.replace(find, replace)

    def extract_emails(self, text: str) -> str:
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        return "Emails found: " + ", ".join(emails) if emails else "No emails found."

    def extract_urls(self, text: str) -> str:
        urls = [u.rstrip(".,;:!?)]}'\"") for u in re.findall(r'https?://[^\s<>"\']+', text, flags=re.IGNORECASE)]
        return "URLs found: " + ", ".join(urls) if urls else "No URLs found."

    def extract_numbers(self, text: str) -> str:
        numbers = re.findall(r"(?<![\d.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|(?<!\d)-?\d+(?:\.\d+)?", text)
        return "Numbers found: " + ", ".join(numbers) if numbers else "No numbers found."

    def slugify(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        return text

    def wrap(self, text: str, width: int = 80) -> str:
        import textwrap
        width = max(int(width), 1)
        lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
        return chr(10).join(lines)

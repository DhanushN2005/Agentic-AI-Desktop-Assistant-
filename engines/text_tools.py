import re


class TextToolsEngine:
    """Text manipulation tools — no API needed."""

    def word_count(self, text: str) -> str:
        words = text.split()
        chars = len(text)
        chars_no_space = len(text.replace(" ", "").replace("\n", ""))
        lines = text.count("\n") + 1
        sentences = len(re.split(r'[.!?]+', text.strip()))
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
        return text.title()

    def sentence_case(self, text: str) -> str:
        if not text:
            return text
        return text[0].upper() + text[1:]

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
        lines = text.split("\n")
        seen = []
        for line in lines:
            if line not in seen:
                seen.append(line)
        return "\n".join(seen)

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
        urls = re.findall(r'https?://[^\s<>\"\']+', text)
        return "URLs found: " + ", ".join(urls) if urls else "No URLs found."

    def extract_numbers(self, text: str) -> str:
        numbers = re.findall(r'-?\d+\.?\d*', text)
        return "Numbers found: " + ", ".join(numbers) if numbers else "No numbers found."

    def slugify(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '-', text)
        return text

    def wrap(self, text: str, width: int = 80) -> str:
        words = text.split()
        lines = []
        current = []
        length = 0
        for word in words:
            if length + len(word) + 1 > width:
                lines.append(" ".join(current))
                current = [word]
                length = len(word)
            else:
                current.append(word)
                length += len(word) + 1
        if current:
            lines.append(" ".join(current))
        return "\n".join(lines)

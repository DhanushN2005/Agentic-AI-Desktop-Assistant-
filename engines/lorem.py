import random


class LoremEngine:
    """Lorem ipsum text generator — no API needed."""

    WORDS = [
        "lorem", "ipsum", "dolor", "sit", "amet", "consectetur", "adipiscing", "elit",
        "sed", "do", "eiusmod", "tempor", "incididunt", "ut", "labore", "et", "dolore",
        "magna", "aliqua", "enim", "ad", "minim", "veniam", "quis", "nostrud",
        "exercitation", "ullamco", "laboris", "nisi", "aliquip", "ex", "ea", "commodo",
        "consequat", "duis", "aute", "irure", "in", "reprehenderit", "voluptate",
        "velit", "esse", "cillum", "fugiat", "nulla", "pariatur", "excepteur", "sint",
        "occaecat", "cupidatat", "non", "proident", "sunt", "culpa", "qui", "officia",
        "deserunt", "mollit", "anim", "id", "est", "laborum", "perspiciatis", "unde",
        "omnis", "iste", "natus", "error", "voluptatem", "accusantium", "doloremque",
        "laudantium", "totam", "rem", "aperiam", "eaque", "ipsa", "quae", "ab", "illo",
        "inventore", "veritatis", "quasi", "architecto", "beatae", "vitae", "dicta",
        "explicabo", "nemo", "ipsam", "quia", "voluptas", "aspernatur", "aut", "odit",
        "fugit", "consequuntur", "magni", "dolores", "ratione", "sequi", "nesciunt",
        "neque", "porro", "quisquam", "nihil", "impedit", "quo", "minus", "maxime",
        "placeat", "facere", "possimus", "omnis", "assumenda", "repellendus", "temporibus",
        "autem", "quibusdam", "officiis", "debitis", "harum", "necessitatibus", "saepe",
        "eveniet", "voluptates", "repudiandae", "intenderit", " molestiae", "non", "recusandae",
        "itaque", "earum", "rerum", "tenetur", "sapiente", "delectus", "reiciendis",
        "voluptatibus", "maiores", "alias", "consequatur", "perferendis", "doloribus",
        "asperiores", "commodi", "assumenda", "repellat"
    ]

    def generate(self, paragraphs: int = 3, sentences_per: int = 5) -> str:
        result = []
        for _ in range(paragraphs):
            para = self._generate_paragraph(sentences_per)
            result.append(para)
        return "\n\n".join(result)

    def _generate_paragraph(self, sentences: int) -> str:
        parts = []
        for _ in range(sentences):
            parts.append(self._generate_sentence())
        return " ".join(parts)

    def _generate_sentence(self) -> str:
        length = random.randint(8, 18)
        words = [random.choice(self.WORDS) for _ in range(length)]
        words[0] = words[0].capitalize()
        return " ".join(words) + "."

    def generate_words(self, count: int = 100) -> str:
        words = [random.choice(self.WORDS) for _ in range(count)]
        words[0] = words[0].capitalize()
        return " ".join(words) + "."

    def generate_list(self, items: int = 5, sentences_per: int = 2) -> str:
        result = []
        for i in range(items):
            para = self._generate_paragraph(sentences_per)
            result.append(f"{i+1}. {para}")
        return "\n".join(result)

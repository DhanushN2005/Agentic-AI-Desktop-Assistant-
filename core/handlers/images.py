import re

_WORD_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20}


def _count(text: str, default: int) -> int:
    m = re.search(r"\b(\d{1,2}|" + "|".join(_WORD_NUMS) + r")\b", text)
    if not m:
        return default
    tok = m.group(1)
    return int(tok) if tok.isdigit() else _WORD_NUMS[tok]


def handle_image_download(orch, c):
    """"download 5 images of cats" / "download images from https://site.com/page"."""
    from engines import image_downloader as dl

    cl = (c or "").lower().strip()
    url = re.search(r"https?://\S+", c or "")
    if url:
        link = url.group(0).rstrip(".,;)")
        orch.speak("Looking for images on that page.")
        res = dl.download_from_page(link, _count(cl.replace(link.lower(), ""), 10))
    else:
        m = re.search(r"(?:images?|pictures?|photos?|pics?|wallpapers?)\s+(?:of|for|about|on|showing)\s+(.+)$", cl)
        query = m.group(1).strip() if m else ""
        if not query:
            m2 = re.search(r"(?:download|save|get|fetch)\s+(?:\w+\s+)?(.+?)\s+(?:images?|pictures?|photos?|pics?)\b", cl)
            query = m2.group(1).strip() if m2 else ""
        query = re.sub(r"\b(?:from\s+)?(?:chrome|google|the\s+web|the\s+internet|online)\b", "", query).strip()
        query = re.sub(r"^(?:\d{1,2}|" + "|".join(_WORD_NUMS) + r")\s+", "", query).strip()
        if not query and re.match(r"^(?:can|could|are you able|do you|will you|is it possible)\b", cl):
            orch.speak("Yes. Say 'download 5 images of cats' and I'll search the web and save them in a new "
                       "folder under Downloads, or give me a page address and I'll save the pictures on it. "
                       "I can't pull images from the tab you're already viewing in your own Chrome.")
            return True
        if not query:
            orch.speak("What should the images show? Say for example 'download 5 images of cats', "
                       "or give me a page address to take the pictures from.")
            return True
        count = _count(cl, 5)
        orch.speak(f"Searching for {count} images of {query}.")
        res = dl.download_by_search(query, count)
    if res.saved:
        orch.ctx.update(last_path=res.folder)
    orch.speak(res.summary())
    return True

import os
import re

from utils.voice_parse import strip_wake

SPOKEN_CAP = 600
_TEXT_EXTS = (".txt", ".md", ".py", ".json")


def downloads_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Downloads")


def newest_file(folder: str, exts: tuple) -> str | None:
    """Most recently modified file with one of exts in folder; None when the
    folder is missing/unreadable or holds no match."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    best, best_mtime = None, -1.0
    for name in names:
        if not name.lower().endswith(exts):
            continue
        full = os.path.join(folder, name)
        try:
            if not os.path.isfile(full):
                continue
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = full, mtime
    return best


def cap_spoken(text: str, cap: int = SPOKEN_CAP) -> str:
    """Trim long text for speech at a sentence/word boundary."""
    if len(text) <= cap:
        return text
    cut = text[:cap]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", cut)]
    if ends and ends[-1] > cap // 2:
        return cut[:ends[-1]].strip() + " The full text is on your screen."
    return cut[:cut.rfind(" ")].strip() + "... The full text is on your screen."


def handle_summarize(orch, c):
    """Handle text summarization commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()

    if any(re.search(rf"\b{w}\b", cmd) for w in ("email", "emails", "mail", "inbox")):
        from core.handlers.mail import handle_mail_summarize
        return handle_mail_summarize(orch, c)

    if "summarize file" in cmd or "summarize document" in cmd or "summary of file" in cmd:
        # path comes from the ORIGINAL text (case-sensitive on many systems)
        path_match = re.search(r"(?:summarize|summary(?:\s+of)?)\s+(?:file|document)\s+(.+)", original, re.IGNORECASE)
        if path_match:
            filepath = path_match.group(1).strip().strip("\"'")
            response = orch.summarizer.summarize_file(filepath)
        else:
            filepath = newest_file(downloads_dir(), _TEXT_EXTS)
            if filepath:
                response = orch.summarizer.summarize_file(filepath)
            else:
                response = "No text files found to summarize."
    elif "summarize url" in cmd or "summarize page" in cmd or "summarize article" in cmd:
        url_match = re.search(r"(https?://\S+)", original, re.IGNORECASE)
        if url_match:
            response = orch.summarizer.summarize_url(url_match.group(1).rstrip(".,;)!?'\""))
        else:
            response = "Please provide a URL to summarize."
    else:
        response = "Say 'summarize file <path>' or 'summarize url <url>'."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(cap_spoken(response))
    return True

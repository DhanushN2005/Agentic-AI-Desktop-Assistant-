import os
import re

from core.handlers.summarize import cap_spoken, downloads_dir, newest_file
from utils.voice_parse import strip_wake

_PATH_RE = re.compile(
    r"(?:read|open|summari[sz]e|analy[sz]e|extract)\s+(?:the\s+)?(?:file\s+)?(?:pdf\s+)?(?:of\s+)?(.+\.pdf)",
    re.IGNORECASE,
)


def handle_pdf(orch, c):
    """Handle PDF-related commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    filepath = None
    path_match = _PATH_RE.search(original)  # ORIGINAL text keeps path case
    scan = original
    if path_match:
        filepath = path_match.group(1).strip().strip("\"'")
        scan = original[:path_match.start(1)] + " " + original[path_match.end(1):]
    cmd = scan.lower()

    if not filepath:
        filepath = newest_file(downloads_dir(), (".pdf",))
        if not filepath:
            response = "No PDF files found. Please specify a file path."
            orch.ctx.update(last_response=response, query=c)
            orch.speak(response)
            return True

    if not os.path.exists(filepath):
        in_downloads = os.path.join(downloads_dir(), filepath)
        if os.path.exists(in_downloads):
            filepath = in_downloads

    if any(w in cmd for w in ["summarize", "summarise", "summary", "brief"]):
        response = orch.pdf_reader.summarize_pdf(filepath)
    elif any(w in cmd for w in ["info", "details", "metadata"]):
        response = orch.pdf_reader.get_info(filepath)
    else:
        response = orch.pdf_reader.read_pdf(filepath)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(cap_spoken(response))
    return True

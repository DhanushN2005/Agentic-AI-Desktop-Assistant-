import re
import os


def handle_pdf(orch, c):
    """Handle PDF-related commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    filepath = None
    path_match = re.search(r'(?:read|open|summarize|analyze|extract)\s+(?:the\s+)?(?:file\s+)?(?:pdf\s+)?(.+\.pdf)', cmd)
    if path_match:
        filepath = path_match.group(1).strip().strip('"').strip("'")

    if not filepath:
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        pdfs = [f for f in os.listdir(downloads) if f.lower().endswith(".pdf")]
        if pdfs:
            filepath = os.path.join(downloads, pdfs[0])
        else:
            response = "No PDF files found. Please specify a file path."
            orch.ctx.update(last_response=response, query=c)
            orch.speak(response)
            return True

    if not os.path.exists(filepath):
        home_pdfs = os.path.join(os.path.expanduser("~"), "Downloads", filepath)
        if os.path.exists(home_pdfs):
            filepath = home_pdfs

    if any(w in cmd for w in ["summarize", "summary", "brief"]):
        response = orch.pdf_reader.summarize_pdf(filepath)
    elif any(w in cmd for w in ["info", "details", "metadata"]):
        response = orch.pdf_reader.get_info(filepath)
    else:
        response = orch.pdf_reader.read_pdf(filepath)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

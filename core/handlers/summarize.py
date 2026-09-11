import re
import os


def handle_summarize(orch, c):
    """Handle text summarization commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "summarize file" in cmd or "summarize document" in cmd:
        path_match = re.search(r"(?:summarize|summary)\s+(?:file|document)\s+(.+)", cmd)
        if path_match:
            filepath = path_match.group(1).strip().strip('"')
            response = orch.summarizer.summarize_file(filepath)
        else:
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            files = [f for f in os.listdir(downloads) if f.endswith((".txt", ".md", ".py", ".json"))]
            if files:
                filepath = os.path.join(downloads, files[0])
                response = orch.summarizer.summarize_file(filepath)
            else:
                response = "No text files found to summarize."
    elif "summarize url" in cmd or "summarize page" in cmd or "summarize article" in cmd:
        url_match = re.search(r"(https?://\S+)", cmd)
        if url_match:
            response = orch.summarizer.summarize_url(url_match.group(1))
        else:
            response = "Please provide a URL to summarize."
    else:
        response = "Say 'summarize file <path>' or 'summarize url <url>'."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

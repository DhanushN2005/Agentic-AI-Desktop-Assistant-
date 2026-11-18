import logging
import os
import re
import uuid
import webbrowser
from urllib.parse import quote

import requests

_PROMPT_RE = re.compile(
    r"^(generate|create|make|draw|design|produce|show me)\s+(an?\s+)?"
    r"(image|picture|photo|pic|artwork|drawing|illustration)\s+(of\s+)?",
    flags=re.IGNORECASE,
)


def _clean_prompt(prompt: str) -> str:
    clean = _PROMPT_RE.sub("", prompt or "").strip()
    return clean or (prompt or "").strip()


class ImageGenEngine:
    """Free image generation using Pollinations AI (no API key required)."""

    API_URL = "https://image.pollinations.ai/prompt/"

    def __init__(self, output_dir: str | None = None):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_dir = output_dir or os.path.join(base, "captures", "generated")
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            logging.debug("[image_gen] cannot create output dir: %s", e)

    def _url(self, clean: str) -> str:
        return f"{self.API_URL}{quote(clean, safe='')}?width=1024&height=1024&nologo=true"

    def generate(self, prompt: str) -> str:
        """Generate an image from a text prompt and save it."""
        clean = _clean_prompt(prompt)
        if not clean:
            return "Please describe the image you want."
        url = self._url(clean)
        filepath = None
        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code != 200:
                return f"Image generation failed (status {resp.status_code})."
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("image/"):
                return "Image generation failed (the service did not return an image)."
            os.makedirs(self.output_dir, exist_ok=True)
            ext = ".jpg" if "jpeg" in ctype or "jpg" in ctype else ".png"
            filepath = os.path.abspath(
                os.path.join(self.output_dir, f"generated_{uuid.uuid4().hex[:12]}{ext}")
            )
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            return f"Image saved to {filepath}"
        except Exception as e:
            logging.debug("[engines/image_gen.py] generation error: %s: %s", type(e).__name__, e)
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            return f"Image generation error: {e}"

    def open_in_browser(self, prompt: str) -> str:
        """Open generated image in browser."""
        clean = _clean_prompt(prompt)
        webbrowser.open(self._url(clean))
        return "Opening generated image in browser."

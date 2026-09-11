import os
import re
import requests
import webbrowser
from urllib.parse import quote_plus


class ImageGenEngine:
    """Free image generation using Pollinations AI (no API key required)."""

    API_URL = "https://image.pollinations.ai/prompt/"

    def __init__(self):
        self.output_dir = os.path.join(os.getcwd(), "captures", "generated")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, prompt: str) -> str:
        """Generate an image from a text prompt and save it."""
        clean = re.sub(r"^(generate|create|make|draw|design|produce|show me)\s+(an?\s+)?(image|picture|photo|pic|artwork|drawing|illustration)\s+(of\s+)?", "", prompt, flags=re.IGNORECASE).strip()
        if not clean:
            clean = prompt

        encoded = quote_plus(clean)
        url = f"{self.API_URL}{encoded}?width=1024&height=1024&nologo=true"

        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code == 200:
                filename = f"generated_{len(os.listdir(self.output_dir)) + 1}.png"
                filepath = os.path.join(self.output_dir, filename)
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                return f"Image saved to {filepath}"
            return f"Image generation failed (status {resp.status_code})."
        except Exception as e:
            return f"Image generation error: {e}"

    def open_in_browser(self, prompt: str) -> str:
        """Open generated image in browser."""
        clean = re.sub(r"^(generate|create|make|draw|design)\s+(an?\s+)?(image|picture|photo|pic|artwork)\s+(of\s+)?", "", prompt, flags=re.IGNORECASE).strip()
        if not clean:
            clean = prompt
        encoded = quote_plus(clean)
        url = f"{self.API_URL}{encoded}?width=1024&height=1024&nologo=true"
        webbrowser.open(url)
        return f"Opening generated image in browser."

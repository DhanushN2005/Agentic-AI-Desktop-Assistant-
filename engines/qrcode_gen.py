import urllib.request
import urllib.parse
import os


class QRCodeEngine:
    """QR code generator — uses free API, no key needed."""

    def generate(self, data: str, size: int = 300) -> str:
        """Generate QR code as image file. Returns file path."""
        try:
            encoded = urllib.parse.quote(data)
            url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                qr_data = resp.read()
                output_dir = os.path.join(os.getcwd(), "captures")
                os.makedirs(output_dir, exist_ok=True)
                filename = f"qr_{hash(data) & 0xFFFF:04x}.png"
                filepath = os.path.join(output_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(qr_data)
                return f"QR code saved to {filepath}"
        except Exception as e:
            return f"Could not generate QR code: {e}"

    def generate_url(self, url: str, size: int = 300) -> str:
        """Generate QR code for a URL."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return self.generate(url, size)

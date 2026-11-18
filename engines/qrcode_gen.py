import hashlib
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from utils.paths import data_dir

MAX_QR_BYTES = 2000  # comfortably inside the QR capacity; larger payloads fail
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class QRCodeEngine:
    """QR code generator.

    Uses a local library (``qrcode`` or ``segno``) when installed.  Only when
    neither is available does it fall back to the api.qrserver.com web API, and
    then the returned message says plainly that the data left this machine.
    """

    def __init__(self, output_dir: str | None = None):
        self.output_dir = output_dir or os.path.join(data_dir(), "data", "qr")

    def _filepath(self, data: str) -> str:
        digest = hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]
        return os.path.join(self.output_dir, f"qr_{digest}.png")

    @staticmethod
    def _local(data: str, filepath: str) -> bool:
        """Render with a local library; False when none is installed."""
        try:
            import qrcode  # type: ignore
            img = qrcode.make(data)
            img.save(filepath)
            return True
        except ImportError:
            pass
        try:
            import segno  # type: ignore
            segno.make(data).save(filepath, scale=8)
            return True
        except ImportError:
            return False

    def generate(self, data: str, size: int = 300) -> str:
        """Generate QR code as image file. Returns a message that starts with
        'QR code saved to' on success and 'Could not generate QR code' on failure."""
        if not data or not data.strip():
            return "Could not generate QR code: there is nothing to encode."
        if len(data.encode("utf-8")) > MAX_QR_BYTES:
            return f"Could not generate QR code: the text is too long ({MAX_QR_BYTES} bytes max)."
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            filepath = self._filepath(data)
            if self._local(data, filepath):
                return f"QR code saved to {filepath}"
        except Exception as e:
            logging.debug("[engines/qrcode_gen.py] local QR failed: %s: %s", type(e).__name__, e)
            return f"Could not generate QR code: {e}"

        # No local library: remote fallback, with an explicit privacy notice.
        try:
            size = max(50, min(int(size), 1000))
            encoded = urllib.parse.quote(data, safe="")
            url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}x{size}&data={encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Flexie/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = getattr(resp, "status", 200)
                qr_data = resp.read()
            if status != 200 or not qr_data.startswith(_PNG_MAGIC):
                return f"Could not generate QR code: the QR web service returned an invalid response (status {status})."
            tmp = filepath + ".part"
            with open(tmp, "wb") as f:
                f.write(qr_data)
            os.replace(tmp, filepath)
            return (f"QR code saved to {filepath}. Note: no local QR library is installed, so the text was "
                    "sent to api.qrserver.com to create it (pip install segno to keep it on this machine).")
        except Exception as e:
            logging.debug("[engines/qrcode_gen.py] remote QR failed: %s: %s", type(e).__name__, e)
            return f"Could not generate QR code: {e}"

    def generate_url(self, url: str, size: int = 300) -> str:
        """Generate QR code for a URL."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return self.generate(url, size)

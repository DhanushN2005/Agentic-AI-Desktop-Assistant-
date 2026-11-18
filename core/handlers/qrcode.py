import re

from utils.voice_parse import strip_wake

_PREFIX = re.compile(
    r"^(?:please\s+)?(?:(?:generate|create|make)\s+(?:an?\s+)?)?(?:qr\s*code|qr)\s*(?:for|of|with|containing)?\s*",
    re.IGNORECASE,
)


def handle_qr(orch, c):
    """Handle QR code generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    # payload from the ORIGINAL text so URLs / case-sensitive data survive
    content = _PREFIX.sub("", original, count=1).strip()
    if len(content) >= 2 and content[0] == content[-1] and content[0] in "\"'":
        content = content[1:-1].strip()

    if not content:
        orch.speak("What should the QR code contain? Say 'generate QR for' followed by text or URL.")
        return True

    response = orch.qrcode_gen.generate(content)
    orch.ctx.update(last_response=response, query=c)
    if response.startswith("QR code saved"):
        spoken = "QR code generated."
        if "api.qrserver.com" in response:
            spoken += " Note that the text was sent to an online service because no local QR library is installed."
        orch.speak(spoken)
    else:
        orch.speak(response)
    return True

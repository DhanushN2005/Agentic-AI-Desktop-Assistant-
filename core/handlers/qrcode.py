import re
import webbrowser


def handle_qr(orch, c):
    """Handle QR code generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    content = re.sub(r"^(qr|qrcode|qr code|generate qr|create qr|make qr)\s*(for|of|with|containing)?\s*", "", cmd, flags=re.IGNORECASE).strip()

    if not content:
        orch.speak("What should the QR code contain? Say 'generate QR for' followed by text or URL.")
        return True

    response = orch.qrcode_gen.generate(content)
    orch.ctx.update(last_response=response, query=c)
    orch.speak(f"QR code generated for: {content}")
    return True

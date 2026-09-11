import re


def handle_hash(orch, c):
    """Handle hash and encoding commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Extract text
    text = re.sub(r"^(md5|sha1|sha256|sha512|base64 encode|base64 decode|hex encode|hex decode|binary encode|binary decode|morse encode|encode|decode|hash)\s*", "", cmd, flags=re.IGNORECASE).strip()
    quote_match = re.search(r'["\'](.+?)["\']', cmd)
    if quote_match:
        text = quote_match.group(1)

    if not text:
        orch.speak("What text should I process?")
        return True

    if "md5" in cmd:
        response = orch.hash_encoder.md5(text)
    elif "sha1" in cmd or "sha-1" in cmd:
        response = orch.hash_encoder.sha1(text)
    elif "sha256" in cmd or "sha-256" in cmd:
        response = orch.hash_encoder.sha256(text)
    elif "sha512" in cmd or "sha-512" in cmd:
        response = orch.hash_encoder.sha512(text)
    elif "base64 encode" in cmd:
        response = orch.hash_encoder.base64_encode(text)
    elif "base64 decode" in cmd:
        response = orch.hash_encoder.base64_decode(text)
    elif "hex encode" in cmd:
        response = orch.hash_encoder.hex_encode(text)
    elif "hex decode" in cmd:
        response = orch.hash_encoder.hex_decode(text)
    elif "binary encode" in cmd:
        response = orch.hash_encoder.binary_encode(text)
    elif "binary decode" in cmd:
        response = orch.hash_encoder.binary_decode(text)
    elif "morse" in cmd:
        response = orch.hash_encoder.morse_encode(text)
    else:
        response = orch.hash_encoder.sha256(text)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

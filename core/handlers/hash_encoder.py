import re

from utils.voice_parse import strip_wake

_FILLER = {
    "md5", "sha1", "sha-1", "sha256", "sha-256", "sha512", "sha-512", "base64", "base-64",
    "hex", "hexadecimal", "binary", "morse", "hash", "hashing", "encode", "decode",
    "encoding", "decoding", "checksum", "digest", "text", "string", "in", "to", "as",
    "of", "for", "with", "me", "give", "compute", "calculate", "generate", "please",
    "this", "get", "make", "create", "code",
}
_ARTICLES = {"the", "a", "an"}
_QUOTE_PAIRS = {'"': '"', "'": "'", "“": "”", "‘": "’", "`": "`"}
_TRAILING = re.compile(
    r"\s+(?:in|to|as|using|with)\s+(?:base-?64|hex(?:adecimal)?|binary|morse|sha-?\d+|md5)\s*$",
    re.IGNORECASE,
)


def _unquote(s: str):
    """Return the inner text when the WHOLE string is wrapped in matching quotes."""
    s = s.strip()
    if len(s) >= 2 and s[0] in _QUOTE_PAIRS and s[-1] == _QUOTE_PAIRS[s[0]]:
        return s[1:-1]
    return None


def _extract_payload(original: str):
    """(payload, keyword_scan_text) from the ORIGINAL text, case preserved.

    The scan text is only the part of the command that is NOT the payload, so a
    payload that happens to contain 'md5' or 'decode' cannot change the operation.
    """
    m = re.search(r'"([^"]*)"|“([^”]*)”', original)
    if m:
        payload = m.group(1) if m.group(1) is not None else m.group(2)
        return payload, (original[:m.start()] + " " + original[m.end():]).lower()
    full = original.strip()
    text = full
    prev_filler = None
    while text:
        parts = text.split(None, 1)
        low = parts[0].lower().strip(":,")
        if low in _FILLER or (low in _ARTICLES and prev_filler in ("of", "for")):
            prev_filler = low
            text = parts[1] if len(parts) > 1 else ""
            continue
        break
    prefix = full[:len(full) - len(text)]
    inner = _unquote(text)
    if inner is not None:
        return inner, prefix.lower()
    trimmed = _TRAILING.sub("", text)
    suffix = text[len(trimmed):]
    return trimmed.strip(), (prefix + " " + suffix).lower()


def handle_hash(orch, c):
    """Handle hash and encoding commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)

    text, scan = _extract_payload(original)

    if not text:
        orch.speak("What text should I process?")
        return True

    def has(*words):
        return any(w in scan for w in words)

    if has("md5"):
        response = orch.hash_encoder.md5(text)
    elif has("sha1", "sha-1"):
        response = orch.hash_encoder.sha1(text)
    elif has("sha256", "sha-256"):
        response = orch.hash_encoder.sha256(text)
    elif has("sha512", "sha-512"):
        response = orch.hash_encoder.sha512(text)
    elif has("base64", "base-64"):
        response = (orch.hash_encoder.base64_decode(text) if has("decode")
                    else orch.hash_encoder.base64_encode(text))
    elif has("hex"):
        response = (orch.hash_encoder.hex_decode(text) if has("decode")
                    else orch.hash_encoder.hex_encode(text))
    elif has("binary"):
        response = (orch.hash_encoder.binary_decode(text) if has("decode")
                    else orch.hash_encoder.binary_encode(text))
    elif has("morse"):
        response = orch.hash_encoder.morse_encode(text)
    else:
        response = orch.hash_encoder.sha256(text)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True

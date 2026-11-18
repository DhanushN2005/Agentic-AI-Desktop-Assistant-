import base64
import binascii
import hashlib
import logging


class HashEncoderEngine:
    """Hash and encoding tools — no API needed."""

    def md5(self, text: str) -> str:
        return f"MD5: {hashlib.md5(text.encode()).hexdigest()}"

    def sha1(self, text: str) -> str:
        return f"SHA-1: {hashlib.sha1(text.encode()).hexdigest()}"

    def sha256(self, text: str) -> str:
        return f"SHA-256: {hashlib.sha256(text.encode()).hexdigest()}"

    def sha512(self, text: str) -> str:
        return f"SHA-512: {hashlib.sha512(text.encode()).hexdigest()}"

    def base64_encode(self, text: str) -> str:
        encoded = base64.b64encode(text.encode()).decode()
        return f"Base64: {encoded}"

    def base64_decode(self, text: str) -> str:
        raw = "".join(text.split())
        if not raw:
            return "Invalid Base64 string."
        try:
            padded = raw + "=" * (-len(raw) % 4)
            if "-" in raw or "_" in raw:
                data = base64.urlsafe_b64decode(padded.encode("ascii"))
            else:
                data = base64.b64decode(padded.encode("ascii"), validate=True)
        except (binascii.Error, ValueError, UnicodeEncodeError) as _e:
            logging.debug("[engines/hash_encoder.py] base64 decode failed: %s: %s", type(_e).__name__, _e)
            return "Invalid Base64 string."
        try:
            return f"Decoded: {data.decode('utf-8')}"
        except UnicodeDecodeError:
            return f"Decoded {len(data)} bytes of non-text data (hex: {data.hex()[:64]})."

    def hex_encode(self, text: str) -> str:
        return f"Hex: {binascii.hexlify(text.encode()).decode()}"

    def hex_decode(self, text: str) -> str:
        raw = "".join(text.split())
        if raw[:2].lower() == "0x":
            raw = raw[2:]
        try:
            data = binascii.unhexlify(raw.encode("ascii"))
        except (binascii.Error, ValueError, UnicodeEncodeError) as _e:
            logging.debug("[engines/hash_encoder.py] hex decode failed: %s: %s", type(_e).__name__, _e)
            return "Invalid hex string (use an even number of 0-9/a-f characters)."
        try:
            return f"Decoded: {data.decode('utf-8')}"
        except UnicodeDecodeError:
            return f"Decoded {len(data)} bytes of non-text data."

    def binary_encode(self, text: str) -> str:
        binary = " ".join(format(b, "08b") for b in text.encode("utf-8"))
        return f"Binary: {binary}"

    def binary_decode(self, text: str) -> str:
        tokens = text.split()
        if not tokens:
            return "Invalid binary string: nothing to decode."
        if len(tokens) == 1 and len(tokens[0]) > 8:
            bits = tokens[0]
            if len(bits) % 8:
                return "Invalid binary string: the length must be a multiple of 8 bits."
            tokens = [bits[k:k + 8] for k in range(0, len(bits), 8)]
        data = bytearray()
        for tok in tokens:
            if not set(tok) <= {"0", "1"}:
                return f"Invalid binary string: '{tok}' contains characters other than 0 and 1."
            if len(tok) > 8:
                return f"Invalid binary group '{tok}': each group must be at most 8 bits."
            data.append(int(tok, 2))
        try:
            return f"Decoded: {bytes(data).decode('utf-8')}"
        except UnicodeDecodeError:
            # fall back to Latin-1 so single-byte values still decode
            return f"Decoded: {bytes(data).decode('latin-1')}"

    def morse_encode(self, text: str) -> str:
        MORSE = {
            'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.',
            'F': '..-.', 'G': '--.', 'H': '....', 'I': '..', 'J': '.---',
            'K': '-.-', 'L': '.-..', 'M': '--', 'N': '-.', 'O': '---',
            'P': '.--.', 'Q': '--.-', 'R': '.-.', 'S': '...', 'T': '-',
            'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-', 'Y': '-.--',
            'Z': '--..', '0': '-----', '1': '.----', '2': '..---',
            '3': '...--', '4': '....-', '5': '.....', '6': '-....',
            '7': '--...', '8': '---..', '9': '----.', ' ': '/'
        }
        result = ' '.join(MORSE.get(c.upper(), '?') for c in text)
        return f"Morse: {result}"

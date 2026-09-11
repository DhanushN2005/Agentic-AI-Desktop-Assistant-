import hashlib
import base64
import binascii


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
        try:
            decoded = base64.b64decode(text.encode()).decode()
            return f"Decoded: {decoded}"
        except Exception:
            return "Invalid Base64 string."

    def hex_encode(self, text: str) -> str:
        return f"Hex: {binascii.hexlify(text.encode()).decode()}"

    def hex_decode(self, text: str) -> str:
        try:
            decoded = binascii.unhexlify(text.encode()).decode()
            return f"Decoded: {decoded}"
        except Exception:
            return "Invalid hex string."

    def binary_encode(self, text: str) -> str:
        binary = ' '.join(format(ord(c), '08b') for c in text)
        return f"Binary: {binary}"

    def binary_decode(self, text: str) -> str:
        try:
            chunks = text.replace(' ', '').split()
            decoded = ''.join(chr(int(chunk, 2)) for chunk in chunks)
            return f"Decoded: {decoded}"
        except Exception:
            return "Invalid binary string."

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
        result = ' '.join(MORSE.get(c.upper(), '') for c in text)
        return f"Morse: {result}"

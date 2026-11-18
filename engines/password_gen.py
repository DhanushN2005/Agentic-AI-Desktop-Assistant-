import random
import secrets
import string

SYMBOLS = "!@#$%^&*()-_=+[]{}|;:,.<>?"
MIN_LENGTH = 8
MAX_LENGTH = 128
_COMMON = {
    "password", "passw0rd", "123456", "12345678", "123456789", "qwerty", "qwerty123",
    "letmein", "welcome", "admin", "iloveyou", "abc123", "111111", "000000",
    "monkey", "dragon", "football", "login", "princess", "secret",
}


class PasswordEngine:
    """Secure password generator — no API needed."""

    def generate(self, length: int = 16, use_upper: bool = True,
                 use_lower: bool = True, use_digits: bool = True,
                 use_symbols: bool = True, min_length: int = MIN_LENGTH) -> str:
        """Generate a password.  Raises ValueError for lengths outside
        [min_length, 128] instead of silently returning a different length."""
        if isinstance(length, bool) or not isinstance(length, int):
            raise ValueError("Password length must be a whole number.")
        if length < min_length:
            raise ValueError(f"Password length must be at least {min_length} characters.")
        if length > MAX_LENGTH:
            raise ValueError(f"Password length must be at most {MAX_LENGTH} characters.")
        chars = ""
        required = []
        if use_lower:
            chars += string.ascii_lowercase
            required.append(secrets.choice(string.ascii_lowercase))
        if use_upper:
            chars += string.ascii_uppercase
            required.append(secrets.choice(string.ascii_uppercase))
        if use_digits:
            chars += string.digits
            required.append(secrets.choice(string.digits))
        if use_symbols:
            symbols = SYMBOLS
            chars += symbols
            required.append(secrets.choice(symbols))

        if not chars:
            chars = string.ascii_letters + string.digits

        remaining = length - len(required)
        if remaining < 0:
            remaining = 0

        password_chars = required + [secrets.choice(chars) for _ in range(remaining)]
        # Shuffle using secrets for cryptographic randomness
        random.SystemRandom().shuffle(password_chars)
        return "".join(password_chars)

    def generate_passphrase(self, word_count: int = 4) -> str:
        """Generate a memorable passphrase using common words."""
        words = [
            "alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
            "golf", "hotel", "india", "juliet", "kilo", "lima",
            "mike", "november", "oscar", "papa", "quebec", "romeo",
            "sierra", "tango", "uniform", "victor", "whiskey", "xray",
            "yankee", "zulu", "apple", "brisk", "creek", "dune",
            "eagle", "flame", "grain", "harbor", "ivory", "jewel",
            "karma", "lemon", "maple", "noble", "ocean", "pearl",
            "quartz", "river", "stone", "tiger", "ultra", "vivid",
            "wheat", "xenon", "yield", "zebra", "coral", "dream",
            "frost", "glow", "haze", "ink", "jade", "knot"
        ]
        if not isinstance(word_count, int) or not 3 <= word_count <= 20:
            raise ValueError("A passphrase needs between 3 and 20 words.")
        chosen = [secrets.choice(words) for _ in range(word_count)]
        separator = secrets.choice(["-", ".", "_", " "])
        return separator.join(chosen)

    def strength_check(self, password: str) -> dict:
        """Check password strength (score 0-6: length x2 tiers + 4 character classes)."""
        score = 0
        feedback = []
        if len(password) >= 8:
            score += 1
        else:
            feedback.append("Use at least 8 characters")
        if len(password) >= 12:
            score += 1
        if any(c.islower() for c in password):
            score += 1
        else:
            feedback.append("Add lowercase letters")
        if any(c.isupper() for c in password):
            score += 1
        else:
            feedback.append("Add uppercase letters")
        if any(c.isdigit() for c in password):
            score += 1
        else:
            feedback.append("Add numbers")
        # any other printable character (incl. space, quotes, ~ ` / \ and unicode symbols)
        if any(not c.isalnum() for c in password):
            score += 1
        else:
            feedback.append("Add symbols")

        if password.lower() in _COMMON:
            score = min(score, 1)
            feedback.append("This is a very common password")
        elif len(set(password)) <= 2 and password:
            score = min(score, 2)
            feedback.append("Avoid repeating the same characters")

        levels = ["Very Weak", "Weak", "Fair", "Good", "Strong", "Very Strong", "Excellent"]
        level = levels[min(score, len(levels) - 1)]
        return {"score": score, "level": level, "feedback": feedback}

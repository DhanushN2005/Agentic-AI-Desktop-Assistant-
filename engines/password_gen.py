import secrets
import string


class PasswordEngine:
    """Secure password generator — no API needed."""

    def generate(self, length: int = 16, use_upper: bool = True,
                 use_lower: bool = True, use_digits: bool = True,
                 use_symbols: bool = True) -> str:
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
            symbols = "!@#$%^&*()-_=+[]{}|;:,.<>?"
            chars += symbols
            required.append(secrets.choice(symbols))

        if not chars:
            chars = string.ascii_letters + string.digits

        remaining = length - len(required)
        if remaining < 0:
            remaining = 0

        password_chars = required + [secrets.choice(chars) for _ in range(remaining)]
        # Shuffle using secrets for cryptographic randomness
        import random
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
        chosen = [secrets.choice(words) for _ in range(word_count)]
        separator = secrets.choice(["-", ".", "_", " "])
        return separator.join(chosen)

    def strength_check(self, password: str) -> dict:
        """Check password strength."""
        score = 0
        feedback = []
        if len(password) >= 8:
            score += 1
        else:
            feedback.append("Use at least 8 characters")
        if len(password) >= 12:
            score += 1
        if any(c in string.ascii_lowercase for c in password):
            score += 1
        else:
            feedback.append("Add lowercase letters")
        if any(c in string.ascii_uppercase for c in password):
            score += 1
        else:
            feedback.append("Add uppercase letters")
        if any(c in string.digits for c in password):
            score += 1
        else:
            feedback.append("Add numbers")
        if any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in password):
            score += 1
        else:
            feedback.append("Add symbols")

        levels = ["Very Weak", "Weak", "Fair", "Good", "Strong", "Very Strong", "Excellent"]
        level = levels[min(score, len(levels) - 1)]
        return {"score": score, "level": level, "feedback": feedback}

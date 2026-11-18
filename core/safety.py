import re
import unicodedata

from utils.config import Config

# Phrases containing a restricted word that are ordinary, harmless speech.
_RESTRICTED_ALLOW = (
    "adult ticket", "adult tickets", "adult education", "adult learning", "adult swim",
    "casino royale", "poker face", "adult fare", "adult size",
)

_restricted_cache: tuple[tuple[str, ...], "re.Pattern | None"] = ((), None)


def normalize_command(text: str) -> str:
    """Canonical form used for safety matching.

    NFKC folds fullwidth/compat characters ("ｒｍ" -> "rm"); format characters (zero-width
    space/joiner, BOM, bidi controls) are removed so "r​m -rf /" cannot slip past; all
    whitespace collapses to single spaces.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", text).strip().lower()


def _restricted_regex() -> "re.Pattern | None":
    """Word-boundary pattern over Config.RESTRICTED_WORDS (rebuilt only if the list changes)."""
    global _restricted_cache
    words = tuple(w.lower() for w in getattr(Config, "RESTRICTED_WORDS", []) if w)
    if _restricted_cache[0] != words:
        pattern = None
        if words:
            alt = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
            pattern = re.compile(rf"(?<![a-z0-9])(?:{alt})(?![a-z0-9])")
        _restricted_cache = (words, pattern)
    return _restricted_cache[1]


def contains_restricted(text: str) -> bool:
    """True if ``text`` contains a restricted WORD (not a substring of a longer word:
    'Essex', 'Sussex' and 'unisex' are fine)."""
    pattern = _restricted_regex()
    if pattern is None or not text:
        return False
    t = normalize_command(text)
    for phrase in _RESTRICTED_ALLOW:
        t = t.replace(phrase, " ")
    return pattern.search(t) is not None


class SafetyGuard:
    """Pre-execution safety layer to validate incoming commands.

    Philosophy:
      - DESTRUCTIVE shell syntax -> rejected outright (never executed).
      - Suspicious metacharacters (``;``, ``&&``, ``||``, backticks, ``$()``)
        -> command is SANITIZED (metacharacters stripped) rather than rejected,
        so legitimate queries like "search for C++ && beginners" still work
        without their shell-metacharacter payload. A raw pipe INTO a shell/interpreter
        or destructive command is always rejected; a bare "|" in prose is allowed.
      - Restricted words -> rejected (content filter, whole words only).
    All matching runs on a normalized copy (NFKC, zero-width characters removed).
    """

    # Regex fragment matching a real invocation target for shell cmdlets:
    # an executable/script path, a quoted string, a drive path, or a flag.
    _TARGET = r"(\S+\.(exe|ps1|bat|cmd|msi)\b|['\"][^'\"]+['\"]|[a-z]:\\|\s-[a-z])"
    _SYSTEM_PATH = r"(?:[a-z]:\\windows|[a-z]:\\boot|[a-z]:\\program files|system32|syswow64|boot\.ini|%systemroot%|%windir%|/etc/|/boot/|/usr/|/bin/|/sbin/)"

    def __init__(self):
        _TARGET, _SYSTEM_PATH = self._TARGET, self._SYSTEM_PATH
        # Matches are case-insensitive (input is lowercased) and anchored to word boundaries so
        # plain-English queries (e.g. "how does sudo work") are NOT flagged, while actual shell
        # usage ("sudo rm -rf /") IS.
        self.blacklist = [
            # Disk / filesystem destruction
            r"\brm\s+(?:-\S+\s*)*-{1,2}(?:[a-z]*[rf][a-z]*|recursive|force|no-preserve-root)\b",
            r"\b(?:del|erase)\b.*\s/[sqfa]\b", r"\bdel\s+-recurse\b",
            r"\b(?:rd|rmdir)\b.*\s/s\b",
            rf"\b(?:del|erase|rm|rd|rmdir|remove-item|ri)\b.*{_SYSTEM_PATH}",
            r"\bformat\s+(?:[a-z]:|/\w|-\w)", r"\bformat-volume\b", r"\bclear-disk\b", r"\bdiskpart\b",
            r"\bmkfs\b", r"\bdd\s+if=", r"\bcipher\s+/w\b",
            # DB destruction (actual SQL statements, not conversation)
            r"\bdrop\s+(?:table|database|schema)\b", r"\btruncate\s+table\b", r"\bgrant\s+all\b",
            r"\bdelete\s+from\s+\w+\s*(?:;|$)",
            # PowerShell / shell remote execution — only when INVOKED with a real target,
            # so conversational mentions pass through.
            # flags first (-Recurse/-Path/-LiteralPath), a drive path, a relative path, a quoted
            # argument, or anything that looks like a file — but not "explain remove-item in powershell"
            r"\bremove-item\s+(?:-\w+|[a-z]:|[.~%$]|['\"]|\S*[\\/]\S*|\S+\.\w{1,5}\b)",
            rf"\bremove-item\s+{_TARGET}",
            r"\bri\s+(?:-\S+|[a-z]:\\|\.{0,2}[\\/]|['\"~%$])",
            rf"\binvoke-expression\s+{_TARGET}",
            r"\biex\s*\(", r"\binvoke-expression\s*\(",
            r"\b(?:powershell|pwsh)\b.*\s-(?:e|ec|enc|encodedcommand)\b",
            r"\b(?:powershell|pwsh)\b.*\b(?:iex|invoke-expression)\b",
            rf"\bstart-process\s+{_TARGET}", r"\bstart-process\b.*-verb\s+runas\b", r"\bsaps\s+\S",
            r"\breg\s+(?:delete|add)\b", r"\bvssadmin\s+delete\b", r"\bbcdedit\b", r"\bwevtutil\s+cl\b",
            # Force-kill / power
            r"\btaskkill\b.*\s/f\b", r"\bkill\s+-9\b", r"\bstop-process\b.*-force\b",
            r"\bshutdown\b(?:\s+\S+)*?\s[/-][srpf]\b", r"\b(?:stop|restart)-computer\b",
            # Piped remote execution — classic injection payloads
            r"\b(?:curl|wget|irm|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*\|\s*(?:sh|bash|zsh|powershell|pwsh|iex|python)\b",
            r"\b(?:curl|wget)\b.*(?:&&|;)\s*(?:sh|bash|\./)",
            # A pipe INTO a shell / interpreter / destructive command
            r"\|\|?\s*(?:sh|bash|zsh|cmd|powershell|pwsh|iex|shutdown|del|rm|format|taskkill|reg)\b",
            # ... and into an interpreter only when the left side is a command that produces
            # code ("search C++ | python" is just prose)
            r"\b(?:cat|type|echo|printf|get-content|curl|wget|irm|iwr)\b[^|]*\|\s*"
            r"(?:python\d?|perl|ruby|node|nc|ncat|certutil|mshta|rundll32)\b",
            # Redirect that overwrites system files
            rf">>?\s*{_SYSTEM_PATH}",
        ]
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.blacklist]

        # Metacharacters that enable shell command chaining / substitution.
        # If present, the command is sanitized (stripped) rather than rejected.
        self._meta_chars = [";", "&&", "||", "|", "`", "$(", ">", "<"]

    def sanitize(self, command: str) -> str:
        """Strip shell metacharacters from a command, preserving safe content.

        URLs are tolerated (':' '/' '&' '?' '=' characters are untouched).
        """
        if not command:
            return command
        cleaned = command
        for ch in self._meta_chars:
            cleaned = cleaned.replace(ch, " ")
        # Collapse runs of whitespace produced by stripping
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned

    def validate(self, command: str) -> bool:
        """Returns True if command is safe to pass to the core engines."""
        cmd = normalize_command(command)

        # 1. System Destruction Patterns (word-boundary aware)
        for pattern in self._compiled:
            if pattern.search(cmd):
                return False

        # 2. Config-based content filtering (whole words only)
        if contains_restricted(cmd):
            return False

        # 3. Active injection payload detection — only REJECT when the
        # metacharacter forms a plausible execution payload (substitution or
        # piping). Plain chaining chars in spoken queries are handled by
        # sanitize() instead of rejecting the whole command.
        if re.search(r"\$\([^)]*\)", cmd):          # $(...) command substitution
            return False
        if re.search(r"`[^`]+`", cmd):               # `...` substitution
            return False

        return True

    def check(self, command: str) -> tuple[bool, str]:
        """Convenience: returns (is_safe, sanitized_command).

        Use this where callers previously did validate() then used the raw
        string — they should pass the sanitized string onward.
        """
        if self.validate(command):
            return True, self.sanitize(command)
        return False, command

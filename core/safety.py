import re

from utils.config import Config


class SafetyGuard:
    """Pre-execution safety layer to validate incoming commands.

    Philosophy:
      - DESTRUCTIVE shell syntax -> rejected outright (never executed).
      - Suspicious metacharacters (``;``, ``&&``, ``||``, backticks, ``$()``)
        -> command is SANITIZED (metacharacters stripped) rather than rejected,
        so legitimate queries like "search for C++ && beginners" still work
        without their shell-metacharacter payload. Raw pipes are always
        rejected because neither URLs nor speech legitimately contain them.
      - Restricted words -> rejected (content filter).
    """

    # Regex fragment matching a real invocation target for shell cmdlets:
    # an executable/script path, a quoted string, a drive path, or a flag.
    _TARGET = r"(\S+\.(exe|ps1|bat|cmd|msi)\b|['\"][^'\"]+['\"]|[a-z]:\\|\s-[a-z])"

    def __init__(self):
        # Word-boundary compiled destructive patterns.
        # Matches are case-insensitive and anchored to word boundaries so
        # plain-English queries (e.g. "how does sudo work") are NOT flagged,
        # while actual shell usage ("sudo rm -rf /") IS.
        self.blacklist = [
            # Disk / filesystem destruction
            r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+", r"\bdel\s+/s", r"\bdel\s+/q",
            r"\brd\s+/s", r"\brmdir\s+/s", r"\bformat\s+(c:|d:|[a-z]:)",
            r"\bformat\s+/y", r"\bmkfs\b", r"\bdd\s+if=",
            # DB destruction (actual SQL statements, not conversation)
            r"\bdrop\s+(table|database)\b", r"\bgrant\s+all\b",
            # PowerShell / shell remote execution — only when INVOKED with a
            # real target, so conversational mentions pass through.
            rf"\bremove-item\s+{self._TARGET}",
            r"\bdel\s+-recurse\b",
            rf"\binvoke-expression\s+{self._TARGET}",
            r"\biex\s+\(",
            r"\bpowershell\s+(-enc|-e\s|.*-encodedcommand)\b",
            r"\bpwsh\s+(-enc|-e\s|.*-encodedcommand)\b",
            rf"\bstart-process\s+{self._TARGET}",
            r"\breg\s+delete\b",
            # Force-kill everything variants
            r"\btaskkill\s+/f\b", r"\bkill\s+-9\b",
            r"\bshutdown\s+/[sr]\s*/f\b", r"\bshutdown\s+/f\b",
            # Piped remote execution — classic injection payloads
            r"\b(curl|wget)\b[^|]*\|\s*(sh|bash|zsh|powershell|iex)\b",
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
        cmd = command.lower().strip()

        # 1. System Destruction Patterns (word-boundary aware)
        for pattern in self._compiled:
            if pattern.search(cmd):
                return False

        # 2. Config-based filtering (Backward compatible)
        for word in Config.RESTRICTED_WORDS:
            if word in cmd:
                return False

        # 3. Active injection payload detection — only REJECT when the
        # metacharacter forms a plausible execution payload (substitution or
        # piping). Plain chaining chars in spoken queries are handled by
        # sanitize() instead of rejecting the whole command.
        if re.search(r"\$\([^)]*\)", cmd):          # $(...) command substitution
            return False
        if re.search(r"`[^`]+`", cmd):               # `...` substitution
            return False
        if "|" in cmd:                               # any raw pipe — URLs and
            return False                             # speech never need it

        return True

    def check(self, command: str) -> tuple[bool, str]:
        """Convenience: returns (is_safe, sanitized_command).

        Use this where callers previously did validate() then used the raw
        string — they should pass the sanitized string onward.
        """
        if self.validate(command):
            return True, self.sanitize(command)
        return False, command

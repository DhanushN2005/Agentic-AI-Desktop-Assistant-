import re


class DangerGate:
    """Detects high-impact commands that must be confirmed by the human user.

    This is a pure classification layer (no I/O), sitting between SafetyGuard
    (which blocks outright-malicious shell commands) and the orchestrator.
    While SafetyGuard stops *destructive syntax*, DangerGate flags *irreversible
    intent* — file deletion, purchases, payments, sends, account actions — so the
    controller can require an explicit spoken confirmation before dispatching.
    """

    def __init__(self):
        self.confirm_phrases = [
            "confirm", "yes", "proceed", "go ahead", "sure",
            "okay", "ok", "yeah", "go for it", "definitely", "execute",
        ]
        self.cancel_phrases = [
            "cancel", "no", "abort", "stop", "don't", "dont", "never mind",
            "skip", "forget it", "leave it",
        ]
        self.danger_patterns = [
            # File / data destruction
            r"\bdelete\b", r"\berase\b", r"\bremove\b", r"\bwipe\b",
            r"\bclear all\b",
            r"\bformat\s+(drive|disk|c:)",
            r"\bempty\s+(the\s+)?(trash|recycle bin)\b",
            # Financial / irreversible side effects
            r"\b(purchase|buy|pay|transfer)\b",
            r"\bmake a payment\b", r"\bconfirm payment\b", r"\bplace an order\b",
            r"\bsend money\b",
            # Account & subscription actions
            r"\bunsubscribe\b", r"\bsign out\b", r"\blog ?out\b",
            r"\bdeactivate\b", r"\bterminate (account|service|subscription)\b",
            r"\bdelete (account|profile)\b",
            # Outbound messaging
            r"\bsend (an? )?(email|mail|whatsapp message|message)\b",
        ]
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.danger_patterns]

        # Word-boundary compiled phrase matchers for confirmation replies.
        self._confirm_re = re.compile(
            "|".join(r"\b" + re.escape(p.strip()) + r"\b" for p in self.confirm_phrases),
            re.IGNORECASE,
        )
        self._cancel_re = re.compile(
            "|".join(r"\b" + re.escape(p.strip()) + r"\b" for p in self.cancel_phrases),
            re.IGNORECASE,
        )
        # Negations that flip an apparent confirmation into a refusal
        # (e.g. "not sure", "don't", "no way", "never").
        self._negation_re = re.compile(
            r"\b(not|no|never|dont|don't|isn't|ain't|can't|cannot|without)\b",
            re.IGNORECASE,
        )

    def detect(self, command: str) -> bool:
        """Returns True if the command matches a high-risk, irreversible intent."""
        if not command:
            return False
        return any(p.search(command) for p in self._compiled)

    def is_confirmation(self, text: str) -> bool:
        """Returns True when the user's reply grants permission."""
        if not text:
            return False
        t = " " + text.lower().strip() + " "
        if self._negation_re.search(t):
            return False
        return self._confirm_re.search(t) is not None

    def is_cancellation(self, text: str) -> bool:
        """Returns True when the user's reply denies permission."""
        if not text:
            return False
        t = " " + text.lower().strip() + " "
        return self._cancel_re.search(t) is not None

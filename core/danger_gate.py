import re

from core.plan_text import split_clauses

# A sentence boundary: ". ", "? ", "! " (not inside 3.5 or a.b), a newline, ';', ': ', or a
# spaced '&' / dash. Splitting here means a harmless question can never hide the action that
# follows it ("what time is it. delete everything").
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|[\r\n]+|;|:\s+|\s+&\s+|\s+[-–—]\s+")


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
            "confirm", "yes", "proceed", "go ahead", "sure", "okay", "ok", "yeah",
            "go for it", "definitely", "execute", "yep", "yup", "y", "do it",
            "sure thing", "affirmative", "absolutely", "please do",
            # common multilingual short confirmations
            "haan", "han", "ji haan", "oui", "si", "ja", "sim",
        ]
        self.cancel_phrases = [
            "cancel", "no", "abort", "stop", "don't", "dont", "never mind",
            "skip", "forget it", "leave it", "nope", "nah", "n", "negative",
            "nahi", "nahin", "non", "nein",
        ]
        self.danger_patterns = [
            # File / data destruction (and its everyday synonyms)
            r"\bdelete\b", r"\berase\b", r"\bremove\b", r"\bwipe\b",
            r"\bclear all\b",
            r"\b(nuke|shred|purge|destroy|obliterate)\b",
            r"\btrash\b(?!\s*(?:can|bin)\b)",
            r"\bget\s+rid\s+of\b", r"\bclear\s+out\b", r"\boverwrite\b",
            r"\buninstall\b", r"\bfactory\s+reset\b", r"\breset\s+(?:the\s+|my\s+)?(?:pc|computer|phone|device)\b",
            r"\bformat\s+(?:the\s+|my\s+)?(?:drive|disk|partition|usb|[a-z]:)",
            r"\bempty\s+(the\s+)?(trash|recycle bin)\b",
            r"\bdrop\s+(?:the\s+)?(?:table|database)\b|\btruncate\s+(?:the\s+)?table\b",
            r"\b(?:clear|wipe|reset)\s+(?:your\s+|my\s+)?memory\b", r"\bforget\s+everything\b",
            # Financial / irreversible side effects
            r"\b(purchase|buy|pay|transfer)\b(?!\s+(?:attention|heed|respect))",
            r"\bmake a payment\b", r"\bconfirm payment\b", r"\bplace an order\b",
            r"\bsend money\b", r"\bsend\s+\$", r"\bwire\s+(?:\$|\d)", r"\b(venmo|donate|withdraw|paypal)\b",
            r"\border\s+(?:a|an|some|me|\d+)\b",
            r"^\s*(?:please\s+)?order\s+(?!by\b|of\b|to\b)\w+",
            r"\bbook\s+(?:a|an|the)?\s*(?:flight|hotel|ticket|cab|table|room)\b",
            # Account & subscription actions
            r"\bunsubscribe\b", r"\bsign out\b", r"\blog ?out\b",
            r"\bdeactivate\b", r"\bterminate (account|service|subscription)\b",
            r"\bdelete (account|profile)\b",
            # Outbound messaging / publishing (judged per clause; verb at the start of the clause)
            r"\bsend (an? )?(email|mail|whatsapp message|message|text)\b",
            r"\breply\s+(?:to\s+)?all\b", r"\bsend\s+(?:it|this|that|them|everything)\b",
            r"\bforward\s+(?:this|it|that|the\s+\w+|everything)\s+to\b",
            r"\bsend\s+\w+\s+an?\s+(?:message|text|email|dm|note)\b",
            r"^\s*(?:please\s+)?(?:email|e-mail|mail|text|message|dm|whatsapp|tweet|post)\s+"
            r"(?!me\b|tools?\b|editor\b|files?\b|box\b|apps?\b|about\b|office\b)\w+",
            r"\b(publish|deploy)\b", r"\bmerge\s+(?:to|into)\s+\w+",
            r"\bgit\s+push\b",
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
            r"\b(not|no|never|dont|don't|isn't|ain't|can't|cannot|without|nahi|nahin|nope|nah|nein|non)\b",
            re.IGNORECASE,
        )

    # A clause that only ASKS about something ("how do I delete a file", "what is a good python
    # tutorial") or stores a reminder is not itself a risky action. Modal questions ("can you
    # delete my files") are requests in disguise and are deliberately NOT treated as benign.
    _INFO_LEAD = re.compile(
        r"^\s*(?:please\s+)?(?:(?:hey\s+)?flexie?[,\s]+)?"
        r"(?:what|who|whom|whose|where|when|why|how(?!\s+about)|which|is|are|was|were|"
        r"explain|define|describe|tell\s+me\s+(?:about|how|what|why)|read\s+about|learn\s+about|"
        r"look\s*up|search(?:\s+the\s+web)?(?:\s+for)?|find\s+out|research|compare)\b",
        re.IGNORECASE,
    )
    # A reminder/note only STORES text. (A trailing word "reminder" is deliberately not enough:
    # "delete everything reminder" must still be flagged.)
    _REMINDER = re.compile(
        r"^\s*(?:please\s+)?(?:remind\s+me\b|(?:set|add|create|make)\s+(?:a\s+)?(?:reminder|note|to-?do)\b|"
        r"take\s+a\s+note\b|note\s+that\b)",
        re.IGNORECASE,
    )

    @classmethod
    def is_benign_clause(cls, clause: str) -> bool:
        """True for a clause that only asks a question or stores a reminder."""
        return bool(clause and (cls._INFO_LEAD.match(clause) or cls._REMINDER.match(clause)))

    @staticmethod
    def clauses(command: str) -> list[str]:
        """Break a command into the pieces that are judged independently: first sentences
        (punctuation, newlines, ';', ':', '&', dashes), then command clauses inside each."""
        out: list[str] = []
        for sentence in _SENTENCE_SPLIT.split(command or ""):
            if sentence and sentence.strip():
                out.extend(split_clauses(sentence) or [sentence.strip()])
        return out or ([command.strip()] if command and command.strip() else [])

    def detect(self, command: str) -> bool:
        """Returns True if the command matches a high-risk, irreversible intent.

        Each sentence and clause is judged on its own, so "search for old files and delete
        them" and "what time is it. delete everything" are flagged (the second part is an
        action) while "how do I delete a file" is not.
        """
        if not command:
            return False
        return any(
            any(p.search(clause) for p in self._compiled)
            for clause in self.clauses(command)
            if not self.is_benign_clause(clause)
        )

    # Words that may appear in a pure approval reply. Anything else (e.g. "ok but first delete
    # everything", "sure, what does that do?") is NOT an approval.
    _FILLER_WORDS = frozenset({
        "please", "flexie", "flexi", "hey", "thanks", "thank", "you",
        "it", "that", "this", "do", "now", "and", "then", "the", "a", "i", "am",
    })
    _MAX_CONFIRM_WORDS = 6

    def is_confirmation(self, text: str) -> bool:
        """True only when the reply is a short, pure approval.

        Fails closed: the reply must consist solely of confirmation vocabulary and
        harmless filler, contain no negation, and be at most a few words long.
        """
        if not text:
            return False
        t = " " + text.lower().strip() + " "
        if self._negation_re.search(t):
            return False
        words = re.findall(r"[a-zà-ÿ']+", t)
        if not words or len(words) > self._MAX_CONFIRM_WORDS:
            return False
        vocab = {w for phrase in self.confirm_phrases for w in re.findall(r"[a-zà-ÿ']+", phrase)}
        allowed = vocab | self._FILLER_WORDS
        if any(w not in allowed for w in words):
            return False
        # Must contain a real approval word, or a whole multi-word phrase such as "do it" /
        # "sure thing" / "go ahead" (whose words are individually just filler).
        joined = " ".join(words)
        if any(" " in p and re.search(r"\b" + re.escape(p) + r"\b", joined) for p in self.confirm_phrases):
            return True
        return any(w in vocab and w not in self._FILLER_WORDS for w in words)

    def is_cancellation(self, text: str) -> bool:
        """Returns True when the user's reply denies permission."""
        if not text:
            return False
        t = " " + text.lower().strip() + " "
        return self._cancel_re.search(t) is not None

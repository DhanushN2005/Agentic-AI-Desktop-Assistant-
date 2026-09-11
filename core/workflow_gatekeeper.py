import re
from enum import Enum, auto

class ClassificationType(Enum):
    DETERMINISTIC = auto()
    SEMANTIC = auto()
    HYBRID = auto()

class WorkflowGatekeeper:
    """
    Intelligent gatekeeper that classifies compound workflows before routing.
    Determines if a workflow can be parsed deterministically, needs full semantic planning,
    or requires hybrid semantic assistance.

    FIX 6: Pronoun detection now uses regex word boundaries (\\b) instead of bare
    substring matching, preventing common words like "it", "this", "that" from
    triggering false SEMANTIC classifications on simple deterministic commands.
    """
    def __init__(self):
        self.dependency_markers = [" because ", " so that ", " if ", " after ", " before "]
        self.hybrid_markers = ["summarize", "explain", "analyze", "research"]

        # FIX 6: Compile word-boundary pronoun patterns once at init to avoid
        # false positives from substring matches (e.g. "submit" matching "it").
        _pronoun_words = ["it", "this", "that", "them"]
        self._pronoun_patterns = [
            re.compile(r"\b" + word + r"\b", re.IGNORECASE)
            for word in _pronoun_words
        ]

    def _has_pronoun(self, cmd_lower: str) -> bool:
        """Returns True only when a standalone pronoun word is found (word boundaries)."""
        return any(pat.search(cmd_lower) for pat in self._pronoun_patterns)

    def classify(self, cmd: str) -> ClassificationType:
        """
        Classifies the incoming compound command.
        """
        cmd_lower = cmd.lower()

        # Check for explicit conditional/temporal dependencies (always semantic)
        if any(marker in cmd_lower for marker in self.dependency_markers):
            return ClassificationType.SEMANTIC

        # FIX 6: Use word-boundary pronoun check — avoids matching "it" inside
        # words like "submit", "this" inside "analysis", "that" inside "catalyst".
        has_pronoun = self._has_pronoun(cmd_lower)
        has_hybrid  = any(marker in cmd_lower for marker in self.hybrid_markers)

        if has_pronoun:
            # Pronoun + hybrid marker (e.g. "summarize that") → hybrid workflow
            if has_hybrid:
                return ClassificationType.HYBRID
            return ClassificationType.SEMANTIC

        # Hybrid markers alone (e.g. "analyze screen") without pronoun reference
        if has_hybrid:
            return ClassificationType.HYBRID

        # Default to deterministic parsing if no explicit complex logic is found
        return ClassificationType.DETERMINISTIC

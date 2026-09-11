import re


class WorkflowParser:
    """
    Deterministic Workflow Parser Layer.
    Extracts simple workflows (A and B) natively without engaging the LLM.
    Escalates to the Semantic Planner ONLY if ambiguity or dependency is detected.

    FIX 6: Ambiguity detection now uses regex word boundaries (\\b) so common
    words like "it", "this", "that" only trigger escalation when they appear as
    standalone words, not as substrings (e.g. "submit", "analysis", "catalyst").
    """

    # Conditional/temporal logic markers — these always need LLM planning
    _CONDITIONAL_MARKERS = ["because", "so that", "if ", "after ", "before "]

    # Compile pronoun word-boundary patterns once at class level
    _PRONOUN_PATTERNS = [
        re.compile(r"\b" + word + r"\b", re.IGNORECASE)
        for word in ["it", "this", "that"]
    ]

    # Filler words to ignore during deterministic parsing
    _FILLER_PATTERNS = [
        re.compile(r"\b" + word + r"\b\s*", re.IGNORECASE)
        for word in ["please", "can you", "could you", "flexie", "kindly", "just", "will you"]
    ]

    @staticmethod
    def _strip_fillers(cmd: str) -> str:
        """Removes common conversational filler words."""
        for pat in WorkflowParser._FILLER_PATTERNS:
            cmd = pat.sub("", cmd)
        return cmd.strip()

    @staticmethod
    def _has_ambiguity(cmd_lower: str) -> bool:
        """
        Returns True only when genuine ambiguity is detected:
        - Conditional/temporal language, OR
        - Standalone pronouns that require context resolution.
        """
        # Conditional markers — always ambiguous
        if any(marker in cmd_lower for marker in WorkflowParser._CONDITIONAL_MARKERS):
            return True
        # FIX 6: Word-boundary pronoun check — avoids false positives from
        # substrings like "submit" (contains "it") or "analysis" (contains "this")
        return any(pat.search(cmd_lower) for pat in WorkflowParser._PRONOUN_PATTERNS)

    @staticmethod
    def parse_simple_workflow(cmd: str) -> tuple[bool, list[str]]:
        """
        Attempts to parse a command deterministically.
        Returns:
            (is_simple_workflow: bool, list_of_steps: List[str])
        """
        cmd_lower = cmd.lower()

        # Remove filler words before analyzing for ambiguity
        cmd_clean = WorkflowParser._strip_fillers(cmd_lower)

        # Escalate to semantic planner if genuine ambiguity is found
        if WorkflowParser._has_ambiguity(cmd_clean):
            return False, []

        # Split simple compound verbs (now supports commas e.g., "A, B, and C",
        # and ", then " without leaking the word "then" into a step).
        # Matches: ", and ", ", then ", ", ", " and ", " then "
        if any(x in cmd_clean for x in [" and ", " then ", ","]):
            parts = re.split(r",\s*(?:and\s+|then\s+)?|\s+(?:and|then)\s+", cmd_clean)
            # Ensure every part has some substance (not just empty strings)
            parts = [p.strip() for p in parts if len(p.strip()) > 2]

            if len(parts) > 1:
                # Do NOT split 2-part code/research + save - they handle save internally
                if len(parts) == 2:
                    first, second = parts[0], parts[1]
                    is_code_research = bool(re.search(r"\b(code|script|program|python|java|research|what\s+is|explain|tell\s+me)\b", first))
                    is_save = bool(re.match(r"^(save|export|write)\b", second))
                    if is_code_research and is_save:
                        return False, []
                return True, parts

        return False, []

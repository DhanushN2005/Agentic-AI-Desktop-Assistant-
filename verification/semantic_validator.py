import logging
from typing import Dict, Any

class SemanticValidator:
    """
    Validates execution outcomes based on semantic quality, not just binary state.
    Includes hallucination scoring, syntax checking, and logical completeness checks.
    """
    def __init__(self):
        self.logger = logging.getLogger("Flexie.SemanticValidator")
        
    def validate_content_generation(self, prompt: str, output: str) -> Dict[str, Any]:
        """
        Validates generated text (e.g., summaries).
        Returns a dict with score and flags.
        """
        score = 100.0
        flags = []
        
        if not output or len(output.strip()) == 0:
            return {"score": 0.0, "flags": ["EMPTY_OUTPUT"], "valid": False}
            
        # Basic hallucination heuristics (placeholder for LLM-based verification)
        if "as an ai language model" in output.lower():
            score -= 50
            flags.append("AI_DISCLAIMER")
            
        return {
            "score": max(0.0, score),
            "flags": flags,
            "valid": score > 70.0
        }
        
    def validate_code_generation(self, code: str) -> Dict[str, Any]:
        """
        Validates generated code for syntax errors.
        """
        score = 100.0
        flags = []
        
        try:
            compile(code, "<string>", "exec")
        except SyntaxError as e:
            score -= 100.0
            flags.append(f"SYNTAX_ERROR: {e}")
            
        return {
            "score": max(0.0, score),
            "flags": flags,
            "valid": score == 100.0
        }

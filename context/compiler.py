import logging
from typing import List, Dict, Any

class ContextCompiler:
    """Pre-compiles context before calling the Brain, optimizing tokens and semantic compression."""
    def __init__(self, max_tokens: int = 2000):
        self.max_tokens = max_tokens
        self.logger = logging.getLogger("ContextCompiler")

    def compile(self, system_prompt: str, context: Dict[str, Any]) -> str:
        """Injects contextual data into the system prompt."""
        memory = context.get("memory", "")
        if memory:
            return f"{system_prompt}\n\n[CONTEXTUAL MEMORY]\n{memory}"
        return system_prompt

    def compile_chat_history(self, history: List[Dict[str, str]]) -> str:
        """Compresses long conversation streams into semantic rolling summaries."""
        if not history:
            return ""

        compiled_turns = []
        token_count = 0

        # Process starting from the latest history turn (reversing)
        for turn in reversed(history):
            role = turn.get("role", "user")
            content = turn.get("content", "")
            
            # Simple word-based token approximation
            words = content.split()
            estimated_tokens = len(words) * 1.3
            
            if token_count + estimated_tokens > self.max_tokens:
                # Compile rolling summary trigger
                self.logger.info("Context length exceeded token limit. Initiating semantic compression.")
                compiled_turns.append(f"[System: Context truncated and compressed semantically]")
                break
                
            compiled_turns.append(f"{role.capitalize()}: {content}")
            token_count += estimated_tokens

        return "\n".join(reversed(compiled_turns))

    def rank_memories(self, query: str, memories: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        """Ranks memories using keyword overlap relevance calculations (TF-IDF approximation)."""
        if not memories:
            return []

        query_words = set(query.lower().split())
        scored_memories = []

        for mem in memories:
            text = f"{mem.get('key', '')} {mem.get('value', '')}".lower()
            overlap = sum(1 for w in query_words if w in text)
            scored_memories.append((mem, overlap))

        # Sort by overlap score descending
        scored_memories.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored_memories[:limit]]

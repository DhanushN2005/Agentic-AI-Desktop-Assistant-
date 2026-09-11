from typing import Dict, Any, List
from agents.base import BaseAgent
from adapters.memory_adapter import LegacyMemoryAdapter

class MemoryAgent(BaseAgent):
    """Memory agent managing standard SQL profiles and semantic memory ranking requests."""
    def __init__(self, memory_adapter: LegacyMemoryAdapter = None):
        super().__init__("memory_agent", "Stateful & Episodic Memory Agent")
        self.adapter = memory_adapter

    def execute_task(self, payload: Dict[str, Any]) -> Any:
        action = payload.get("action", "").lower().strip()
        key = payload.get("key", "").strip()
        value = payload.get("value", "").strip()
        query = payload.get("query", "").strip()

        self.logger.info(f"MemoryAgent executing action: {action}")

        # Try to use semantic memory v2 (Phase 2 vector index)
        try:
            from core.vector_store import VectorStore
            vector_store = VectorStore()
        except Exception as ve:
            self.logger.warning(f"Vector V2 store unavailable: {ve}")
            vector_store = None

        if action == "store_episodic" and query:
            if vector_store:
                vector_store.add_episode(query, value)
                return "Episode stored in semantic vector database."
            return "Failed to store episode: Vector store unavailable."
            
        elif action == "recall_episodic" and query:
            if vector_store:
                results = vector_store.search_episodes(query, limit=3)
                return results
            return "Failed to recall: Vector store unavailable."

        elif action == "set_preference" and key:
            if self.adapter:
                self.adapter.set_preference(key, value)
                return f"Preference '{key}' updated."
                
        elif action == "get_preference" and key:
            if self.adapter:
                return self.adapter.get_preference(key, value) # value is default here

        return f"Action '{action}' is not supported or adapter is missing."

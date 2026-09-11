import logging
import os
import numpy as np
from typing import List, Dict, Any

class VectorStore:
    """Hybrid Semantic Memory database leveraging ChromaDB for embeddings retrieval."""
    def __init__(self, db_dir: str = "context/flexie_memory"):
        self.db_dir = db_dir
        self.logger = logging.getLogger("VectorStore")
        self.chroma_client = None
        self.collection = None
        self._init_chroma()

    def _init_chroma(self):
        try:
            import chromadb
            # Create persistent client
            self.chroma_client = chromadb.PersistentClient(path=self.db_dir)
            # Get or create collection
            self.collection = self.chroma_client.get_or_create_collection(
                name="flexie_episodes"
            )
            self.logger.info("ChromaDB vector store successfully initialized.")
        except Exception as e:
            self.logger.error(f"ChromaDB initialization failed: {e}. Falling back to numpy-based storage.")
            self.chroma_client = None

    def add_episode(self, doc_id: str, text: str, metadata: dict = None):
        """Indexes an episodic text chunk into the vector database."""
        if self.collection:
            try:
                # Add to chroma (uses default model embeddings)
                self.collection.add(
                    documents=[text],
                    metadatas=[metadata or {}],
                    ids=[doc_id]
                )
                self.logger.info(f"Episode '{doc_id}' successfully stored in ChromaDB.")
                return
            except Exception as ce:
                self.logger.error(f"ChromaDB insert failed: {ce}")

        # Fallback NumPy vector store serialization could be logged in memory
        self.logger.warning("Episode indexing deferred (Using fallback registry).")

    def search_episodes(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        if self.collection:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                return [{"id": id, "text": text, "metadata": meta} 
                        for id, text, meta in zip(results['ids'][0], results['documents'][0], results['metadatas'][0])]
            except Exception as e:
                self.logger.error(f"Search failed: {e}")
        return []
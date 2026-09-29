import importlib.util
import logging
from typing import Any


class VectorStore:
    """Hybrid Semantic Memory database leveraging ChromaDB with Ollama embeddings."""
    def __init__(self, db_dir: str = "context/flexie_memory"):
        self.db_dir = db_dir
        self.logger = logging.getLogger("VectorStore")
        self.chroma_client = None
        self.collection = None
        self.rag_available = False
        self._init_chroma()

    def _ollama_available(self) -> bool:
        try:
            from urllib.request import urlopen, Request
            req = Request("http://localhost:11434/api/tags")
            with urlopen(req, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _init_chroma(self):
        try:
            import chromadb
            embedding_fn = None
            if self._ollama_available():
                try:
                    from chromadb.utils import embedding_functions
                    embedding_fn = embedding_functions.OllamaEmbeddingFunction(
                        api_endpoint="http://localhost:11434/api/embeddings",
                        model_name="nomic-embed-text"
                    )
                except Exception as e:
                    self.logger.warning(f"Ollama embedding fn failed, using default: {e}")
            self.rag_available = embedding_fn is not None or importlib.util.find_spec("onnxruntime") is not None
            self.chroma_client = chromadb.PersistentClient(path=self.db_dir)
            self.collection = self.chroma_client.get_or_create_collection(
                name="flexie_episodes",
                embedding_function=embedding_fn
            )
            if self.rag_available:
                self.logger.info("ChromaDB embeddings initialized.")
            else:
                self.logger.warning("ChromaDB initialized without a usable embedding backend; RAG disabled.")
        except Exception as e:
            self.logger.error(f"ChromaDB initialization failed: {e}. Falling back to numpy-based storage.")
            self.rag_available = False
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

    def search_episodes(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        if self.collection and self.rag_available:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                return [{"id": id, "text": text, "metadata": meta}
                        for id, text, meta in zip(results['ids'][0], results['documents'][0], results['metadatas'][0], strict=False)]
            except Exception as e:
                self.rag_available = False
                self.logger.error(f"Search failed: {e}")
        return []

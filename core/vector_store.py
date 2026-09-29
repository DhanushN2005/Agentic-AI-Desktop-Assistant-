import importlib.util
import logging
import time
from typing import Any


def _ollama_base() -> str:
    """Ollama host derived from Config.OLLAMA_URL (no hardcoded localhost)."""
    try:
        from urllib.parse import urlparse
        from utils.config import Config
        raw = getattr(Config, "OLLAMA_URL", "") or "http://localhost:11434/api/generate"
        parts = urlparse(raw)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    except Exception:
        pass
    return "http://localhost:11434"


class VectorStore:
    """Hybrid Semantic Memory database leveraging ChromaDB with Ollama embeddings."""
    # Retry policy for transient Chroma failures (no permanent disable).
    _MAX_CONSEC_ERRORS = 5
    _COOLDOWN_SECONDS = 60.0
    _MAX_PENDING = 100

    def __init__(self, db_dir: str = "context/flexie_memory"):
        self.db_dir = db_dir
        self.logger = logging.getLogger("VectorStore")
        self.chroma_client = None
        self.collection = None
        self.rag_available = False
        self._consec_errors = 0
        self._cooldown_until = 0.0
        self._pending: list[tuple[str, str, dict]] = []
        self._init_chroma()

    def _ollama_available(self) -> bool:
        try:
            from urllib.request import urlopen, Request
            req = Request(f"{_ollama_base()}/api/tags")
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
                        api_endpoint=f"{_ollama_base()}/api/embeddings",
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

    def _note_success(self):
        self._consec_errors = 0
        self._cooldown_until = 0.0
        if self.collection is not None:
            self.rag_available = True
        self._flush_pending()

    def _note_error(self, where: str, exc: Exception):
        self._consec_errors += 1
        self.logger.warning(f"VectorStore {where} failed ({self._consec_errors}x): {exc}")
        if self._consec_errors >= self._MAX_CONSEC_ERRORS:
            # Temporary cooldown, NOT a permanent disable — search retries after it.
            self._cooldown_until = time.monotonic() + self._COOLDOWN_SECONDS
            self.logger.warning(
                f"VectorStore backing off for {self._COOLDOWN_SECONDS:.0f}s after "
                f"{self._consec_errors} consecutive errors."
            )

    def _in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def _flush_pending(self):
        """Retry queued episodes; keep leftovers queued (bounded), never silently drop."""
        if not self._pending or self.collection is None:
            return
        still_pending = []
        for doc_id, text, metadata in self._pending:
            try:
                self.collection.add(documents=[text], metadatas=[metadata or {}], ids=[doc_id])
            except Exception as e:
                self.logger.warning(f"VectorStore pending replay failed for '{doc_id}': {e}")
                still_pending.append((doc_id, text, metadata))
        dropped = len(self._pending) - len(still_pending)
        self._pending = still_pending[-self._MAX_PENDING:]
        if dropped:
            self.logger.info(f"VectorStore replayed {dropped} queued episode(s).")
        if self._pending:
            self.logger.warning(f"VectorStore still holding {len(self._pending)} queued episode(s).")

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
                self._note_success()
                return
            except Exception as ce:
                self._note_error("insert", ce)

        # Queue for later replay instead of silently dropping.
        self._pending.append((doc_id, text, metadata or {}))
        if len(self._pending) > self._MAX_PENDING:
            overflow = self._pending.pop(0)
            self.logger.error(f"VectorStore queue full — dropping oldest episode '{overflow[0]}'.")
        self.logger.warning(f"Episode '{doc_id}' queued ({len(self._pending)} pending).")

    def search_episodes(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        if self._in_cooldown():
            return []
        if self.collection and self.rag_available:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                self._note_success()
                return [{"id": id, "text": text, "metadata": meta}
                        for id, text, meta in zip(results['ids'][0], results['documents'][0], results['metadatas'][0], strict=False)]
            except Exception as e:
                self._note_error("search", e)
        return []

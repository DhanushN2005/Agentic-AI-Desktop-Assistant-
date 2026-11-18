import hashlib
import importlib.util
import logging
import re
import threading
import time
from typing import Any

from core.memory_manager import contains_secret
from utils.paths import data_file


def _ollama_base() -> str:
    """Ollama host derived from Config.OLLAMA_URL (no hardcoded localhost)."""
    try:
        from urllib.parse import urlparse

        from utils.config import Config
        raw = getattr(Config, "OLLAMA_URL", "") or "http://localhost:11434/api/generate"
        parts = urlparse(raw)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    except Exception as _e:
        logging.debug("[core/vector_store.py:17] Swallowed exception: %s: %s", type(_e).__name__, _e)
    return "http://localhost:11434"


class VectorStore:
    """Hybrid Semantic Memory database leveraging ChromaDB with Ollama embeddings."""
    # Retry policy for transient Chroma failures (no permanent disable).
    _MAX_CONSEC_ERRORS = 5
    _COOLDOWN_SECONDS = 60.0
    _MAX_PENDING = 100

    EMBED_MODEL = "nomic-embed-text"
    _FORGET_PAGE = 500
    _INIT_WAIT_SECONDS = 30.0

    def __init__(self, db_dir: str | None = None):
        # Anchored to the project (not the working directory), like every other data file.
        self.db_dir = db_dir or data_file("context/flexie_memory")
        self.collection_name = "flexie_episodes"
        self.logger = logging.getLogger("VectorStore")
        self._chroma_client = None
        self._collection = None
        self._rag_available = False
        self._consec_errors = 0
        self._cooldown_until = 0.0
        self._pending: list[tuple[str, str, dict]] = []
        # Importing chromadb and probing Ollama costs ~6 s; do it off the startup path. Any
        # access to the collection waits for it (bounded), so callers see no API change.
        self._ready = threading.Event()
        self._init_thread = threading.Thread(target=self._init_in_background, name="vector-init", daemon=True)
        self._init_thread.start()

    def _init_in_background(self):
        try:
            self._init_chroma()
        finally:
            self._ready.set()

    _collection = None
    _chroma_client = None
    _rag_available = False
    _collection_name = "flexie_episodes"

    def _wait_ready(self):
        ready = self.__dict__.get("_ready")
        if ready is not None and not ready.is_set() and threading.current_thread() is not self.__dict__.get("_init_thread"):
            ready.wait(self._INIT_WAIT_SECONDS)

    @property
    def collection_name(self):
        self._wait_ready()
        return self._collection_name

    @collection_name.setter
    def collection_name(self, value):
        self._collection_name = value

    @property
    def collection(self):
        self._wait_ready()
        return self._collection

    @collection.setter
    def collection(self, value):
        self._collection = value

    @property
    def chroma_client(self):
        self._wait_ready()
        return self._chroma_client

    @chroma_client.setter
    def chroma_client(self, value):
        self._chroma_client = value

    @property
    def rag_available(self):
        self._wait_ready()
        return self._rag_available

    @rag_available.setter
    def rag_available(self, value):
        self._rag_available = value

    def _ollama_available(self) -> bool:
        try:
            from urllib.request import Request, urlopen
            req = Request(f"{_ollama_base()}/api/tags")
            with urlopen(req, timeout=0.8) as r:
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
                        model_name=self.EMBED_MODEL
                    )
                    # Different embedding models have different vector dimensions: a
                    # collection created with one must never be queried with another.
                    tag = re.sub(r"[^A-Za-z0-9_-]", "-", self.EMBED_MODEL)[:40]
                    self.collection_name = f"flexie_episodes_{tag}"
                except Exception as e:
                    self.logger.warning(f"Ollama embedding fn failed, using default: {e}")
            self.rag_available = embedding_fn is not None or importlib.util.find_spec("onnxruntime") is not None
            self.chroma_client = chromadb.PersistentClient(path=self.db_dir)
            self.collection = self.chroma_client.get_or_create_collection(
                name=self.collection_name,
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

    @staticmethod
    def _unique_id(doc_id: str, text: str) -> str:
        """Same id + same text is idempotent; same id + different text must not collide."""
        return f"{doc_id}-{hashlib.sha1((text or '').encode('utf-8', 'replace')).hexdigest()[:8]}"

    def add_episode(self, doc_id: str, text: str, metadata: dict = None):
        """Indexes an episodic text chunk into the vector database.

        Text containing secrets (passwords, keys, OTPs...) is never indexed.
        """
        if contains_secret(text):
            self.logger.info(f"Episode '{doc_id}' skipped: contains secret-like text.")
            return
        doc_id = self._unique_id(doc_id, text)
        metadata = dict(metadata or {})
        metadata.setdefault("ts", time.time())   # lets prune_older_than() age episodes out
        if self.collection:
            try:
                self.collection.add(documents=[text], metadatas=[metadata], ids=[doc_id])
                self.logger.info(f"Episode '{doc_id}' successfully stored in ChromaDB.")
                self._note_success()
                return
            except Exception as ce:
                self._note_error("insert", ce)

        # Queue for later replay instead of silently dropping.
        self._pending.append((doc_id, text, metadata))
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

    def forget_matching(self, text: str, limit: int | None = None) -> int:  # noqa: ARG002
        """Delete every indexed episode whose text contains ``text`` (case-insensitive).

        Pages through the whole collection (no 20-hit truncation), so a common term does
        not leave matches behind. Also drops queued episodes. ``limit`` is accepted for
        backward compatibility and ignored.
        """
        needle = text.lower().strip()
        if not needle:
            return 0
        removed = 0
        kept = [p for p in self._pending if needle not in p[1].lower()]
        removed += len(self._pending) - len(kept)
        self._pending = kept
        if self.collection:
            try:
                ids: list[str] = []
                offset = 0
                while True:
                    res = self.collection.get(include=["documents"], limit=self._FORGET_PAGE, offset=offset)
                    page_ids = res.get("ids", []) or []
                    docs = res.get("documents", []) or []
                    ids.extend(i for i, d in zip(page_ids, docs, strict=False) if d and needle in d.lower())
                    if len(page_ids) < self._FORGET_PAGE:
                        break
                    offset += self._FORGET_PAGE
                for i in range(0, len(ids), self._FORGET_PAGE):
                    self.collection.delete(ids=ids[i:i + self._FORGET_PAGE])
                removed += len(ids)
            except Exception as e:
                self._note_error("forget", e)
                raise
        return removed

    def prune_older_than(self, days: float = 30.0) -> int:
        """Delete episodes indexed more than ``days`` ago (episodes without a timestamp are kept)."""
        if not self.collection:
            return 0
        cutoff = time.time() - days * 86400.0
        try:
            res = self.collection.get(where={"ts": {"$lt": cutoff}}, include=[])
            ids = res.get("ids", []) or []
            for i in range(0, len(ids), self._FORGET_PAGE):
                self.collection.delete(ids=ids[i:i + self._FORGET_PAGE])
            return len(ids)
        except Exception as e:
            self._note_error("prune", e)
            return 0

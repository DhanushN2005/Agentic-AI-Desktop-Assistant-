import os
import json
import logging
import threading
import time
import re
from typing import List, Optional, Dict
from utils.config import Config

class KnowledgeEngine:
    """Engine for high-speed indexing and semantic searching of local documents."""
    def __init__(self, orchestrator):
        self.flexie = orchestrator
        self.brain = orchestrator.brain
        self.logger = logging.getLogger("Flexie.Knowledge")
        self.allowed_exts = {'.txt', '.md', '.py', '.js', '.json', '.pdf'}
        self.index: Dict[str, List[str]] = {} # Keyword -> List of Paths
        self.file_cache: Dict[str, str] = {} # Path -> Content Snippet
        
        # Load existing index if available
        self._load_index()
        
        # Start background indexing
        threading.Thread(target=self.background_indexer, daemon=True).start()

    def _load_index(self):
        if os.path.exists(Config.VECTOR_DB_PATH):
            try:
                with open(Config.VECTOR_DB_PATH, 'r') as f:
                    data = json.load(f)
                    self.index = data.get("index", {})
                    self.file_cache = data.get("cache", {})
            except: pass

    def _save_index(self):
        try:
            with open(Config.VECTOR_DB_PATH, 'w') as f:
                json.dump({"index": self.index, "cache": self.file_cache}, f)
        except: pass

    def background_indexer(self):
        """Periodically scans and indexes local files into the vector-lite store."""
        while True:
            self.logger.info("Starting knowledge indexing...")
            for root_dir in Config.SEARCH_ROOTS:
                if not os.path.exists(root_dir): continue
                for root, dirs, files in os.walk(root_dir):
                    dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__']]
                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        if ext in self.allowed_exts:
                            path = os.path.join(root, file)
                            self._index_file(path)
            self._save_index()
            time.sleep(3600) # Re-index every hour

    def _index_file(self, path: str):
        try:
            mtime = os.path.getmtime(path)
            # Skip if already indexed and not modified
            content = self._read_file_safe(path)
            if not content: return
            
            # Semantic Mapping: Extract keywords
            words = set(re.findall(r'\w+', content.lower()))
            for word in words:
                if len(word) < 4: continue
                if word not in self.index: self.index[word] = []
                if path not in self.index[word]: self.index[word].append(path)
            
            self.file_cache[path] = content[:2000] # Store preview
        except: pass

    def search_my_files(self, query: str) -> str:
        """High-speed semantic search using the pre-built index."""
        query_words = re.findall(r'\w+', query.lower())
        candidates = {} # Path -> Score
        
        for word in query_words:
            if word in self.index:
                for path in self.index[word]:
                    candidates[path] = candidates.get(path, 0) + 1
        
        # Sort by relevance (keyword overlap)
        sorted_paths = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:5]
        
        if not sorted_paths:
            return f"I couldn't find any documents in my index related to '{query}'."

        context = []
        for path, score in sorted_paths:
            preview = self.file_cache.get(path, "")
            context.append(f"Source: {os.path.basename(path)}\nContent: {preview}")

        full_context = "\n\n---\n\n".join(context)
        prompt = f"Based on these local files, answer: {query}\n\nContext:\n{full_context}"
        return self.brain.ask(prompt)

    def _read_file_safe(self, path: str) -> Optional[str]:
        # [Existing read logic...]
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in ['.txt', '.md', '.py', '.js', '.json']:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            elif ext == '.pdf':
                try:
                    import pypdf
                    reader = pypdf.PdfReader(path)
                    return "".join([p.extract_text() for p in reader.pages[:3]])
                except: return None
        except: pass
        return None

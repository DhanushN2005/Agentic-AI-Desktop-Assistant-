"""Bounded, shared file/folder name index (EN-10/11).

One index is used by the file manager, the music engine and (for the shared
exclusion rules) the knowledge indexer.  It replaces repeated ``os.walk`` scans
of whole drives with a single depth/size-capped ``os.scandir`` walk that is
refreshed in the background and can be queried in O(1) for exact names.

Exclusions are made on PATH COMPONENTS (never substrings), so a folder called
"Windows Projects" is indexed while ``C:\\Windows`` and ``...\\AppData`` are not.
"""
from __future__ import annotations

import logging
import os
import threading
import time

EXCLUDED_COMPONENTS = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", "node_modules", ".git", "__pycache__", "site-packages",
    "venv", ".venv", "$recycle.bin", "system volume information",
    "recovery", "msocache",
})

DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_ENTRIES = 150_000


def is_excluded_component(name: str) -> bool:
    """True when a single path component (not a substring) must be skipped."""
    low = name.lower()
    return low in EXCLUDED_COMPONENTS or low.startswith("$") or low.startswith(".")


def path_has_excluded_component(path: str) -> bool:
    parts = [p for p in os.path.normpath(path).split(os.sep) if p and not p.endswith(":")]
    return any(is_excluded_component(p) for p in parts)


class NameIndex:
    def __init__(self, roots=None, max_depth: int = DEFAULT_MAX_DEPTH,
                 max_entries: int = DEFAULT_MAX_ENTRIES, ttl: float = 900.0):
        self._roots = list(roots) if roots is not None else None
        self.max_depth = max_depth
        self.max_entries = max_entries
        self.ttl = ttl
        self._lock = threading.Lock()
        self._by_name: dict[str, list[str]] = {}
        self._built_at = 0.0
        self._building = False

    # ------------------------------------------------------------------ roots
    def roots(self) -> list[str]:
        if self._roots is not None:
            return list(self._roots)
        try:
            from utils.config import Config
            return list(Config.SEARCH_ROOTS)
        except Exception:
            return [os.path.expanduser("~")]

    # ------------------------------------------------------------------ build
    def build(self) -> int:
        """Synchronously rebuild the index; returns number of entries."""
        by_name: dict[str, list[str]] = {}
        count = 0
        for root in self.roots():
            if not root or not os.path.isdir(root):
                continue
            stack = [(root, 0)]
            while stack and count < self.max_entries:
                cur, depth = stack.pop()
                try:
                    with os.scandir(cur) as it:
                        for e in it:
                            try:
                                is_dir = e.is_dir(follow_symlinks=False)
                            except OSError:
                                continue
                            if is_dir and is_excluded_component(e.name):
                                continue
                            by_name.setdefault(e.name.lower(), []).append(e.path)
                            count += 1
                            if is_dir and depth < self.max_depth:
                                stack.append((e.path, depth + 1))
                            if count >= self.max_entries:
                                break
                except OSError:
                    continue
        with self._lock:
            self._by_name = by_name
            self._built_at = time.monotonic()
            self._building = False
        return count

    def refresh_async(self, force: bool = False) -> None:
        with self._lock:
            fresh = self._built_at and (time.monotonic() - self._built_at) < self.ttl
            if self._building or (fresh and not force):
                return
            self._building = True

        def _run():
            try:
                self.build()
            except Exception as e:  # pragma: no cover
                logging.debug("name index build failed: %s", e)
                with self._lock:
                    self._building = False
        threading.Thread(target=_run, daemon=True, name="name-index").start()

    # ----------------------------------------------------------------- lookup
    def _snapshot(self) -> dict[str, list[str]]:
        with self._lock:
            return self._by_name

    def exact(self, name: str) -> list[str]:
        """Paths whose basename equals ``name`` (case-insensitive), existing only."""
        return [p for p in self._snapshot().get(name.lower(), []) if os.path.exists(p)]

    def partial(self, text: str, limit: int = 8) -> list[str]:
        t = text.lower()
        out: list[str] = []
        if not t:
            return out
        for n, paths in self._snapshot().items():
            if t in n:
                for p in paths:
                    if os.path.exists(p):
                        out.append(p)
                        if len(out) >= limit:
                            return out
        return out

    def names(self) -> set[str]:
        return set(self._snapshot().keys())

    def find_by_ext(self, text: str, exts, limit: int = 10) -> list[str]:
        t = text.lower()
        exts = {e.lower() for e in exts}
        out: list[str] = []
        for n, paths in self._snapshot().items():
            if t in n and os.path.splitext(n)[1] in exts:
                out.extend(p for p in paths if os.path.isfile(p))
                if len(out) >= limit:
                    break
        return out[:limit]

    def ready(self) -> bool:
        return bool(self._built_at)


_shared: NameIndex | None = None
_shared_lock = threading.Lock()


def get_shared_index() -> NameIndex:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = NameIndex()
        return _shared

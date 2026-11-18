"""Shared, thread-safe SQLite connections for the small, frequently written memory databases.

Opening and closing a connection per write costs ~14 ms on Windows (journal files are
created and deleted every time) regardless of fsync settings. A single cached connection
per database file in WAL mode with ``synchronous=NORMAL`` costs ~0.05 ms per write.

``fast_connect(path)`` is a drop-in for ``sqlite3.connect(path)`` in the memory stores:
it returns a lightweight proxy over the cached connection. ``close()`` is a no-op (the
connection lives for the process), ``with`` commits/rolls back but does not close, and
every statement is serialised by a per-database lock with results fetched eagerly, so
threads never interleave on the shared connection.

Durability: WAL + NORMAL keeps the database consistent after an application crash. Only
the most recent commits can be lost on an OS crash or power failure, which is acceptable
for assistant memory.
"""
from __future__ import annotations

import atexit
import os
import sqlite3
import threading
from typing import Any

_registry: dict[str, _Shared] = {}
_registry_lock = threading.Lock()


class _Shared:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass  # read-only media etc.: keep the default mode


class _Result:
    """Eagerly materialised cursor result (safe to read after the lock is released)."""

    def __init__(self, rows: list, rowcount: int, lastrowid: int | None, description: Any):
        self._rows = rows
        self._pos = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = description

    def fetchall(self) -> list:
        rows, self._pos = self._rows[self._pos:], len(self._rows)
        return rows

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchmany(self, size: int = 1) -> list:
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class _Proxy:
    def __init__(self, shared: _Shared):
        self._s = shared
        self.rowcount = -1
        self.lastrowid = None
        self._last: _Result | None = None

    def execute(self, sql: str, params: Any = ()) -> _Result:
        with self._s.lock:
            cur = self._s.conn.execute(sql, params)
            res = _Result(cur.fetchall(), cur.rowcount, cur.lastrowid, cur.description)
        self.rowcount, self.lastrowid, self._last = res.rowcount, res.lastrowid, res
        return res

    def executemany(self, sql: str, seq: Any) -> _Result:
        with self._s.lock:
            cur = self._s.conn.executemany(sql, seq)
            res = _Result([], cur.rowcount, cur.lastrowid, cur.description)
        self.rowcount, self.lastrowid, self._last = res.rowcount, res.lastrowid, res
        return res

    def executescript(self, script: str) -> None:
        with self._s.lock:
            self._s.conn.executescript(script)

    def cursor(self) -> _Proxy:
        return _Proxy(self._s)  # statements are serialised by the shared lock anyway

    # Cursor-style reads (``c = conn.cursor(); c.execute(...); c.fetchall()``).
    def fetchall(self) -> list:
        return self._last.fetchall() if self._last else []

    def fetchone(self):
        return self._last.fetchone() if self._last else None

    def fetchmany(self, size: int = 1) -> list:
        return self._last.fetchmany(size) if self._last else []

    def __iter__(self):
        return iter(self.fetchall())

    def commit(self) -> None:
        with self._s.lock:
            self._s.conn.commit()

    def rollback(self) -> None:
        with self._s.lock:
            self._s.conn.rollback()

    def close(self) -> None:
        """No-op: the connection is shared and lives for the process."""

    def __enter__(self) -> _Proxy:
        self._s.lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._s.conn.commit()
            else:
                self._s.conn.rollback()
        finally:
            self._s.lock.release()
        return False


def fast_connect(path: str, timeout: float = 10.0) -> _Proxy:  # noqa: ARG001  (timeout kept for API parity)
    key = os.path.abspath(path)
    with _registry_lock:
        shared = _registry.get(key)
        if shared is None:
            shared = _registry[key] = _Shared(key)
    return _Proxy(shared)


def close_all() -> None:
    """Close every shared connection (process exit, or tests that delete database files)."""
    with _registry_lock:
        for shared in _registry.values():
            try:
                with shared.lock:
                    shared.conn.close()
            except sqlite3.Error:
                pass
        _registry.clear()


atexit.register(close_all)

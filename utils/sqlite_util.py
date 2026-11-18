"""Shared, thread-safe SQLite connections for the small, frequently written memory databases.

Opening and closing a connection per write costs ~14 ms on Windows (journal files are
created and deleted every time) regardless of fsync settings. A single cached connection
per database file in WAL mode with ``synchronous=NORMAL`` costs ~0.05 ms per write.

``fast_connect(path)`` is a drop-in for ``sqlite3.connect(path)`` in the memory stores:
it returns a lightweight proxy over the cached connection. ``close()`` is a no-op (the
connection lives for the process), ``with`` commits/rolls back but does not close, and
every statement is serialised by a per-database lock with results fetched eagerly.

Transactions never interleave: every statement outside a ``with proxy:`` block
auto-commits before the lock is released, so one caller's commit/rollback can never
touch another caller's half-finished work. ``with proxy:`` holds the per-database lock
from entry to exit (one transaction, committed or rolled back as a unit; nested blocks
use SAVEPOINTs). An explicit ``BEGIN`` statement holds the lock until its COMMIT/ROLLBACK.

Durability: WAL + NORMAL keeps the database consistent after an application crash. Only
the most recent commits can be lost on an OS crash or power failure, which is acceptable
for assistant memory. ``close_all()`` (also run at exit) checkpoints the WAL.
"""
from __future__ import annotations

import atexit
import os
import sqlite3
import threading
from typing import Any

_registry: dict[str, _Shared] = {}
_registry_lock = threading.Lock()
_exiting = False


class _Shared:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.conn: sqlite3.Connection | None = None
        self.depth = 0          # open ``with proxy:`` blocks (changed only by the lock holder)
        self.manual = False     # an explicit BEGIN is open (lock held until it ends)
        self._open()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass  # read-only media etc.: keep the default mode
        self.conn = conn
        return conn

    def get(self) -> sqlite3.Connection:
        """The live connection; reopened (and still tracked) if close_all() closed it."""
        conn = self.conn
        if conn is None:
            conn = self._open()
        return conn

    def finish_write(self, conn: sqlite3.Connection) -> None:
        """Auto-commit unless a transaction scope owns the pending work."""
        if self.depth or self.manual:
            return
        if conn.in_transaction:
            conn.commit()
        if _exiting:
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass

    def close(self) -> None:
        if not self.lock.acquire(timeout=5.0):   # a thread died inside BEGIN: don't hang exit
            return
        try:
            conn, self.conn = self.conn, None
            if conn is None:
                return
            try:
                if conn.in_transaction:
                    conn.commit()
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
            finally:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self.depth = 0
            self.manual = False
        finally:
            self.lock.release()


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


def _first_word(sql: str) -> str:
    parts = sql.lstrip().split(None, 1)
    return parts[0].upper().rstrip(";") if parts else ""


class _Proxy:
    def __init__(self, shared: _Shared):
        self._s = shared
        self.rowcount = -1
        self.lastrowid = None
        self._last: _Result | None = None
        self._sp: list[str] = []   # savepoint names of this proxy's open ``with`` blocks

    def execute(self, sql: str, params: Any = ()) -> _Result:
        s = self._s
        with s.lock:
            conn = s.get()
            word = _first_word(sql)
            began = False
            if word == "BEGIN" and not s.manual and not s.depth:
                s.lock.acquire()      # held until the matching COMMIT/ROLLBACK
                s.manual = began = True
            try:
                cur = conn.execute(sql, params)
            except Exception:
                if began:
                    s.manual = False
                    s.lock.release()
                elif not (s.depth or s.manual) and conn.in_transaction:
                    conn.rollback()   # undo only this caller's failed work
                raise
            res = _Result(cur.fetchall(), cur.rowcount, cur.lastrowid, cur.description)
            if (s.manual and not s.depth and word in ("COMMIT", "END", "ROLLBACK")
                    and "TO" not in sql.upper().split()):
                s.manual = False
                s.lock.release()
            else:
                s.finish_write(conn)
        self.rowcount, self.lastrowid, self._last = res.rowcount, res.lastrowid, res
        return res

    def executemany(self, sql: str, seq: Any) -> _Result:
        s = self._s
        with s.lock:
            conn = s.get()
            try:
                cur = conn.executemany(sql, seq)
            except Exception:
                if not (s.depth or s.manual) and conn.in_transaction:
                    conn.rollback()   # all-or-nothing batch
                raise
            res = _Result([], cur.rowcount, cur.lastrowid, cur.description)
            s.finish_write(conn)
        self.rowcount, self.lastrowid, self._last = res.rowcount, res.lastrowid, res
        return res

    def executescript(self, script: str) -> None:
        with self._s.lock:
            self._s.get().executescript(script)

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

    def _end_manual(self) -> None:
        s = self._s
        if s.manual and not s.depth:
            s.manual = False
            s.lock.release()

    def commit(self) -> None:
        with self._s.lock:
            self._s.get().commit()
            self._end_manual()

    def rollback(self) -> None:
        with self._s.lock:
            self._s.get().rollback()
            self._end_manual()

    def close(self) -> None:
        """No-op: the connection is shared and lives for the process."""

    def __enter__(self) -> _Proxy:
        s = self._s
        s.lock.acquire()
        try:
            conn = s.get()
            if s.depth:
                name = f"sp{s.depth}"
                conn.execute(f"SAVEPOINT {name}")
                self._sp.append(name)
            else:
                self._sp.append("")
            s.depth += 1
        except BaseException:
            s.lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        s = self._s
        name = self._sp.pop() if self._sp else ""
        try:
            conn = s.get()
            s.depth = max(0, s.depth - 1)
            if name:
                if exc_type is None:
                    conn.execute(f"RELEASE {name}")
                else:
                    conn.execute(f"ROLLBACK TO {name}")
                    conn.execute(f"RELEASE {name}")
            elif exc_type is None:
                conn.commit()
            else:
                conn.rollback()
            if not s.depth:
                s.finish_write(conn)
        finally:
            s.lock.release()
        return False


def fast_connect(path: str, timeout: float = 10.0) -> _Proxy:  # noqa: ARG001  (timeout kept for API parity)
    key = os.path.abspath(path)
    with _registry_lock:
        shared = _registry.get(key)
        if shared is None:
            shared = _registry[key] = _Shared(key)
    return _Proxy(shared)


def close_all() -> None:
    """Checkpoint and close every shared connection.

    Entries stay registered: a write that arrives later (late thread, or tests that
    delete database files) transparently reopens the connection, which is tracked and
    closed by the next ``close_all()``. After the exit hook ran, a reopened connection
    also checkpoints after each commit, so late writes reach the main database file.
    """
    with _registry_lock:
        shareds = list(_registry.values())
    for shared in shareds:
        try:
            shared.close()
        except Exception:
            pass


def _close_at_exit() -> None:
    global _exiting
    close_all()
    _exiting = True


atexit.register(_close_at_exit)

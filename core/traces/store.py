"""SQLite-backed trace store."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from core.telemetry.redact import redact_secrets
from core.traces.trace import StepType, Trace, TraceStep

_DB_ENV = "FLEXIE_TRACES_DB"
_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "traces.db"


class TraceStore:
    def __init__(self, db_path: str | os.PathLike | None = None, retention_days: float | None = None):
        path = Path(db_path or os.getenv(_DB_ENV) or _DEFAULT_DB)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:  # one persistent connection: WAL + NORMAL keeps per-trace writes cheap
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        self._ensure_schema()
        if retention_days is None:
            try:
                retention_days = float(os.getenv("FLEXIE_RETENTION_DAYS", "30"))
            except ValueError:
                retention_days = 30.0
        self.prune(retention_days)

    def prune(self, retention_days: float | None = 30.0) -> int:
        """Delete traces (and their steps) older than ``retention_days``; <= 0 / None disables."""
        if not retention_days or retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400.0
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "DELETE FROM trace_steps WHERE trace_id IN (SELECT trace_id FROM traces WHERE started_at < ?)",
                    (cutoff,))
                cur = self._conn.execute("DELETE FROM traces WHERE started_at < ?", (cutoff,))
                return int(cur.rowcount or 0)
        except sqlite3.DatabaseError:
            return 0

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    query TEXT,
                    agent TEXT,
                    model TEXT,
                    engine TEXT,
                    result TEXT,
                    outcome TEXT,
                    feedback REAL,
                    started_at REAL,
                    ended_at REAL,
                    total_tokens INTEGER,
                    total_latency_seconds REAL,
                    metadata TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    step_type TEXT,
                    timestamp REAL,
                    duration_seconds REAL,
                    input TEXT,
                    output TEXT,
                    metadata TEXT,
                    FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_steps_trace ON trace_steps(trace_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at)")

    def save(self, trace: Trace) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO traces (
                    trace_id, query, agent, model, engine, result, outcome,
                    feedback, started_at, ended_at, total_tokens,
                    total_latency_seconds, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    redact_secrets(trace.query),
                    trace.agent,
                    trace.model,
                    trace.engine,
                    redact_secrets(trace.result),
                    trace.outcome,
                    trace.feedback,
                    trace.started_at,
                    trace.ended_at,
                    trace.total_tokens,
                    trace.total_latency_seconds,
                    redact_secrets(json.dumps(trace.metadata)),
                ),
            )
            self._conn.execute("DELETE FROM trace_steps WHERE trace_id = ?", (trace.trace_id,))
            for step in trace.steps:
                self._conn.execute(
                    """
                    INSERT INTO trace_steps (
                        trace_id, step_type, timestamp, duration_seconds,
                        input, output, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.trace_id,
                        step.step_type.value,
                        step.timestamp,
                        step.duration_seconds,
                        redact_secrets(json.dumps(step.input)),
                        redact_secrets(json.dumps(step.output)),
                        redact_secrets(json.dumps(step.metadata)),
                    ),
                )

    @staticmethod
    def _to_trace(row: sqlite3.Row, step_rows: list[sqlite3.Row]) -> Trace:
        steps = [
            TraceStep(
                step_type=StepType(step["step_type"]),
                timestamp=step["timestamp"],
                duration_seconds=step["duration_seconds"],
                input=json.loads(step["input"] or "{}"),
                output=json.loads(step["output"] or "{}"),
                metadata=json.loads(step["metadata"] or "{}"),
            )
            for step in step_rows
        ]
        return Trace(
            query=row["query"],
            trace_id=row["trace_id"],
            agent=row["agent"] or "",
            model=row["model"] or "",
            engine=row["engine"] or "",
            steps=steps,
            result=row["result"] or "",
            outcome=row["outcome"],
            feedback=row["feedback"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            total_tokens=row["total_tokens"] or 0,
            total_latency_seconds=row["total_latency_seconds"] or 0.0,
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def get(self, trace_id: str) -> Trace | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if not row:
                return None
            step_rows = self._conn.execute(
                "SELECT * FROM trace_steps WHERE trace_id = ? ORDER BY id", (trace_id,)
            ).fetchall()
        return self._to_trace(row, step_rows)

    def list_traces(self, limit: int = 100, outcome: str | None = None) -> list[Trace]:
        """Newest first. Two queries total (traces, then all their steps), not 1 + 2N."""
        sql = "SELECT * FROM traces"
        params: list[Any] = []
        if outcome:
            sql += " WHERE outcome = ?"
            params.append(outcome)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            steps_by_trace: dict[str, list[sqlite3.Row]] = {}
            ids = [r["trace_id"] for r in rows]
            for i in range(0, len(ids), 500):  # stay under SQLite's variable limit
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for srow in self._conn.execute(
                    f"SELECT * FROM trace_steps WHERE trace_id IN ({marks}) ORDER BY id", chunk
                ):
                    steps_by_trace.setdefault(srow["trace_id"], []).append(srow)
        return [self._to_trace(r, steps_by_trace.get(r["trace_id"], [])) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

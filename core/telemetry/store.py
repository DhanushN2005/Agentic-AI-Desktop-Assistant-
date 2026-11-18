"""SQLite-backed telemetry store with basic aggregation."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from core.telemetry.record import TelemetryRecord

_DB_ENV = "FLEXIE_TELEMETRY_DB"
_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "telemetry.db"


class TelemetryStore:
    def __init__(self, db_path: str | os.PathLike | None = None):
        path = Path(db_path or os.getenv(_DB_ENV) or _DEFAULT_DB)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:  # one persistent connection: WAL + NORMAL makes per-call writes cheap
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            pass
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    model_id TEXT,
                    engine TEXT,
                    agent TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    latency_seconds REAL,
                    ttft REAL,
                    cost_usd REAL,
                    energy_joules REAL,
                    power_watts REAL,
                    metadata TEXT
                )
                """
            )
            # Migration: databases created before per-command attribution lack this column.
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(telemetry)")}
            if "command_id" not in columns:
                self._conn.execute("ALTER TABLE telemetry ADD COLUMN command_id TEXT")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_command ON telemetry(command_id)")

    def record(self, record: TelemetryRecord) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO telemetry (
                    timestamp, model_id, engine, agent, prompt_tokens,
                    completion_tokens, total_tokens, latency_seconds, ttft,
                    cost_usd, energy_joules, power_watts, metadata, command_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.timestamp,
                    record.model_id,
                    record.engine,
                    record.agent,
                    record.prompt_tokens,
                    record.completion_tokens,
                    record.total_tokens,
                    record.latency_seconds,
                    record.ttft,
                    record.cost_usd,
                    record.energy_joules,
                    record.power_watts,
                    json.dumps(record.metadata),
                    record.command_id or None,
                ),
            )
            return int(cursor.lastrowid)

    def _rows(self, since: float | None = None, until: float | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM telemetry"
        clauses, params = [], []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def summary(self, since: float | None = None, until: float | None = None) -> dict[str, Any]:
        rows = self._rows(since, until)
        per_model: dict[str, dict[str, Any]] = {}
        per_engine: dict[str, dict[str, Any]] = {}
        for row in rows:
            for bucket, key in ((per_model, row["model_id"]), (per_engine, row["engine"])):
                key = key or "unknown"
                stats = bucket.setdefault(
                    key, {"calls": 0, "tokens": 0, "cost": 0.0, "latency": 0.0}
                )
                stats["calls"] += 1
                stats["tokens"] += row["total_tokens"] or 0
                stats["cost"] += row["cost_usd"] or 0.0
                stats["latency"] += row["latency_seconds"] or 0.0
        return {
            "total_calls": len(rows),
            "total_tokens": sum((row["total_tokens"] or 0) for row in rows),
            "total_cost": sum((row["cost_usd"] or 0.0) for row in rows),
            "total_latency": sum((row["latency_seconds"] or 0.0) for row in rows),
            "per_model": per_model,
            "per_engine": per_engine,
        }

    def export_records(self, since: float | None = None, until: float | None = None) -> list[dict[str, Any]]:
        out = []
        for row in self._rows(since, until):
            item = dict(row)
            item["metadata"] = json.loads(item.get("metadata") or "{}")
            out.append(item)
        return out

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0])

    def clear(self) -> int:
        with self._lock, self._conn:
            count = int(self._conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0])
            self._conn.execute("DELETE FROM telemetry")
            return count

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def command_summary(self, command_id: str) -> dict[str, Any]:
        """Totals for every recorded LLM call made while serving one command."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM telemetry WHERE command_id = ?", (command_id,)).fetchall()
        return {
            "command_id": command_id,
            "calls": len(rows),
            "tokens": sum((r["total_tokens"] or 0) for r in rows),
            "cost_usd": sum((r["cost_usd"] or 0.0) for r in rows),
            "latency_seconds": sum((r["latency_seconds"] or 0.0) for r in rows),
        }

    def top_commands(self, limit: int = 10, by: str = "cost_usd") -> list[dict[str, Any]]:
        """The most expensive (or token-heavy) commands."""
        order = "tokens" if by == "tokens" else "cost_usd"
        with self._lock:
            rows = self._conn.execute(
                "SELECT command_id, COUNT(*) AS calls, SUM(total_tokens) AS tokens, "
                "SUM(cost_usd) AS cost_usd, SUM(latency_seconds) AS latency_seconds "
                "FROM telemetry WHERE command_id IS NOT NULL AND command_id != '' "
                f"GROUP BY command_id ORDER BY {order} DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

"""Data models for Build Jobs."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_USER = "waiting_user"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DONE = "done"


@dataclass
class JobPhase:
    name: str
    status: str = "pending"  # pending, running, done, failed, skipped
    output: str = ""
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    git_commit: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JobPhase:
        return cls(
            name=data.get("name", "unnamed_phase"),
            status=data.get("status", "pending"),
            output=data.get("output", ""),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            git_commit=data.get("git_commit"),
            error=data.get("error"),
        )


@dataclass
class BuildJob:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    request_text: str = ""
    phase_list: List[JobPhase] = field(default_factory=list)
    status: JobStatus = JobStatus.QUEUED
    current_phase: int = 0
    attempts: int = 0
    log_path: str = ""
    workspace_path: str = ""
    tokens_used: int = 0
    elapsed_seconds: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "request_text": self.request_text,
            "phase_list": [p.to_dict() for p in self.phase_list],
            "status": self.status.value if isinstance(self.status, JobStatus) else str(self.status),
            "current_phase": self.current_phase,
            "attempts": self.attempts,
            "log_path": self.log_path,
            "workspace_path": self.workspace_path,
            "tokens_used": self.tokens_used,
            "elapsed_seconds": self.elapsed_seconds,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BuildJob:
        raw_status = data.get("status", JobStatus.QUEUED.value)
        try:
            status_enum = JobStatus(raw_status)
        except ValueError:
            status_enum = JobStatus.QUEUED

        phases = [
            p if isinstance(p, JobPhase) else JobPhase.from_dict(p)
            for p in data.get("phase_list", [])
        ]

        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            title=data.get("title", ""),
            request_text=data.get("request_text", ""),
            phase_list=phases,
            status=status_enum,
            current_phase=int(data.get("current_phase", 0)),
            attempts=int(data.get("attempts", 0)),
            log_path=data.get("log_path", ""),
            workspace_path=data.get("workspace_path", ""),
            tokens_used=int(data.get("tokens_used", 0)),
            elapsed_seconds=float(data.get("elapsed_seconds", 0.0)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

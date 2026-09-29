"""Atomic JSON persistence for Build Jobs."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Dict, List, Optional

from core.jobs.models import BuildJob

logger = logging.getLogger("flexie.jobs.store")


class JobStore:
    """Manages on-disk state storage for BuildJobs with atomic writes."""

    def __init__(self, storage_dir: str):
        self.storage_dir = os.path.realpath(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _job_file(self, job_id: str) -> str:
        safe_id = "".join(c for c in job_id if c.isalnum() or c in ("-", "_"))
        return os.path.join(self.storage_dir, f"{safe_id}.json")

    def save(self, job: BuildJob) -> bool:
        """Atomically persist job to <storage_dir>/<job_id>.json."""
        with self._lock:
            dest_file = self._job_file(job.id)
            try:
                # Write to temp file in the same directory for atomic rename
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=self.storage_dir, prefix=f".{job.id}_", suffix=".tmp"
                )
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(job.to_dict(), f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, dest_file)
                return True
            except Exception as e:
                logger.error("Failed to atomically save job %s: %s", job.id, e)
                if "tmp_path" in locals() and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                return False

    def load(self, job_id: str) -> Optional[BuildJob]:
        """Load job by ID from disk."""
        dest_file = self._job_file(job_id)
        if not os.path.exists(dest_file):
            return None
        with self._lock:
            try:
                with open(dest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return BuildJob.from_dict(data)
            except Exception as e:
                logger.error("Failed loading job %s: %s", job_id, e)
                return None

    def list_all(self) -> List[BuildJob]:
        """List all persisted jobs ordered by created_at descending."""
        jobs: List[BuildJob] = []
        if not os.path.exists(self.storage_dir):
            return jobs
        with self._lock:
            for fname in os.listdir(self.storage_dir):
                if fname.endswith(".json") and not fname.startswith("."):
                    path = os.path.join(self.storage_dir, fname)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        jobs.append(BuildJob.from_dict(data))
                    except Exception as e:
                        logger.warning("Corrupted job file %s: %s", fname, e)
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def delete(self, job_id: str) -> bool:
        """Remove job file from disk."""
        dest_file = self._job_file(job_id)
        with self._lock:
            if os.path.exists(dest_file):
                try:
                    os.remove(dest_file)
                    return True
                except Exception as e:
                    logger.error("Failed deleting job %s: %s", job_id, e)
                    return False
        return False

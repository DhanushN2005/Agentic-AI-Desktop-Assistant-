"""Atomic JSON persistence for Build Jobs."""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time

from core.jobs.models import BuildJob

logger = logging.getLogger("flexie.jobs.store")

_REPLACE_RETRIES = 6


class StoreError(OSError):
    """Raised by ``save(..., raise_on_error=True)`` when persistence fails."""


class JobStore:
    """Manages on-disk state storage for BuildJobs with atomic writes.

    Each ``<id>.json`` has a ``<id>.json.bak`` holding the previous good version.
    Corrupt files are quarantined (renamed ``*.corrupt-<ts>``) instead of being
    silently skipped, and the ``.bak`` is used to recover the job when possible.
    """

    def __init__(self, storage_dir: str):
        self.storage_dir = os.path.realpath(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self._lock = threading.RLock()
        self.last_error: str | None = None
        self.quarantined: list[str] = []

    def _job_file(self, job_id: str) -> str:
        safe_id = "".join(c for c in str(job_id) if c.isalnum() or c in ("-", "_"))
        return os.path.join(self.storage_dir, f"{safe_id}.json")

    # ------------------------------------------------------------------ write
    def save(self, job: BuildJob, raise_on_error: bool = False) -> bool:
        """Atomically persist job to <storage_dir>/<job_id>.json.

        Returns False on failure (and records ``last_error``); with
        ``raise_on_error=True`` a StoreError is raised instead.
        """
        with self._lock:
            dest_file = self._job_file(job.id)
            tmp_path = ""
            try:
                payload = json.dumps(job.to_dict(), indent=2)
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=self.storage_dir, prefix=f".{job.id}_", suffix=".tmp"
                )
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                if os.path.exists(dest_file):
                    with contextlib.suppress(OSError):
                        shutil.copy2(dest_file, dest_file + ".bak")
                self._replace_with_retry(tmp_path, dest_file)
                self.last_error = None
                return True
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.error("Failed to atomically save job %s: %s", job.id, e)
                if tmp_path and os.path.exists(tmp_path):
                    with contextlib.suppress(Exception):
                        os.remove(tmp_path)
                if raise_on_error:
                    raise StoreError(f"could not persist job {job.id}: {e}") from e
                return False

    @staticmethod
    def _replace_with_retry(src: str, dst: str) -> None:
        delay = 0.05
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                # Windows: AV/indexer/reader briefly holds the destination open.
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.5)

    # ------------------------------------------------------------------- read
    def _quarantine(self, path: str, reason: str) -> None:
        target = f"{path}.corrupt-{int(time.time())}"
        try:
            os.replace(path, target)
            self.quarantined.append(target)
            logger.error("Corrupt job file %s quarantined as %s (%s)", path, target, reason)
        except OSError as e:
            logger.error("Corrupt job file %s could not be quarantined: %s", path, e)

    def _read_path(self, path: str) -> BuildJob | None:
        """Read one job file; quarantine if corrupt and fall back to its .bak."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("job JSON is not an object")
            return BuildJob.from_dict(data)
        except FileNotFoundError:
            return None
        except Exception as e:
            self._quarantine(path, f"{type(e).__name__}: {e}")
        bak = path + ".bak"
        if os.path.exists(bak):
            try:
                with open(bak, encoding="utf-8") as f:
                    data = json.load(f)
                job = BuildJob.from_dict(data)
                with contextlib.suppress(OSError):
                    shutil.copy2(bak, path)
                logger.warning("Recovered job %s from backup", job.id)
                return job
            except Exception as e2:
                logger.error("Backup %s also unreadable: %s", bak, e2)
        return None

    def load(self, job_id: str) -> BuildJob | None:
        """Load job by ID from disk."""
        dest_file = self._job_file(job_id)
        with self._lock:
            if not os.path.exists(dest_file):
                return None
            return self._read_path(dest_file)

    def list_all(self) -> list[BuildJob]:
        """List all persisted jobs ordered by created_at descending."""
        jobs: list[BuildJob] = []
        with self._lock:
            if not os.path.exists(self.storage_dir):
                return jobs
            for fname in sorted(os.listdir(self.storage_dir)):
                if fname.endswith(".json") and not fname.startswith("."):
                    job = self._read_path(os.path.join(self.storage_dir, fname))
                    if job is not None:
                        jobs.append(job)
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def delete(self, job_id: str) -> bool:
        """Remove job file from disk."""
        dest_file = self._job_file(job_id)
        with self._lock:
            if os.path.exists(dest_file):
                try:
                    os.remove(dest_file)
                    with contextlib.suppress(OSError):
                        os.remove(dest_file + ".bak")
                    return True
                except Exception as e:
                    logger.error("Failed deleting job %s: %s", job_id, e)
                    return False
        return False

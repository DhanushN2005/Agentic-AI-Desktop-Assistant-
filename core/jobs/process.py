"""Process tree management and cooperative cancellation utilities."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from typing import Dict, List, Optional

logger = logging.getLogger("flexie.jobs.process")


def kill_process_tree(pid: int) -> bool:
    """Terminate a process and all of its spawned children cleanly without crashing."""
    if pid <= 0:
        return False

    success = False
    # Method 1: Windows taskkill /T /F
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
            if res.returncode == 0:
                logger.info("Process tree for PID %s killed via taskkill", pid)
                return True
        except Exception as e:
            logger.debug("taskkill failed for PID %s: %s", pid, e)

    # Method 2: psutil fallback (cross-platform)
    try:
        import psutil
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
        logger.info("Process tree for PID %s killed via psutil", pid)
        return True
    except Exception as pe:
        logger.debug("psutil tree kill failed for PID %s: %s", pid, pe)

    # Method 3: Standard os.kill fallback
    try:
        import signal
        os.kill(pid, signal.SIGTERM)
        success = True
    except Exception:
        pass

    return success


class ProcessTracker:
    """Thread-safe registry of running subprocesses tied to jobs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._procs: Dict[str, List[subprocess.Popen]] = {}

    def register(self, job_id: str, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.setdefault(job_id, []).append(proc)

    def unregister(self, job_id: str, proc: subprocess.Popen) -> None:
        with self._lock:
            if job_id in self._procs and proc in self._procs[job_id]:
                self._procs[job_id].remove(proc)

    def kill_all(self, job_id: str) -> None:
        with self._lock:
            procs = list(self._procs.get(job_id, []))
        for p in procs:
            if p.poll() is None:
                try:
                    kill_process_tree(p.pid)
                except Exception as e:
                    logger.warning("Error killing proc PID %s for job %s: %s", getattr(p, "pid", None), job_id, e)
        with self._lock:
            self._procs.pop(job_id, None)

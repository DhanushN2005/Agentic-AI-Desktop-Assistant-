import logging
import os
import threading
import time
from collections.abc import Callable

import psutil


class Worker:
    """Represents a supervised lifecycle worker."""
    def __init__(self, name: str, run_fn: Callable[[], None], restart_on_fail: bool = True):
        self.name = name
        self.run_fn = run_fn
        self.restart_on_fail = restart_on_fail
        self.thread: threading.Thread = None
        self.last_heartbeat = time.time()
        self.failures_count = 0
        self.active = False

class Supervisor:
    """Supervisor Runtime Daemon to monitor components, manage lifecycle, and perform zombie cleanup."""
    def __init__(self):
        self.workers: dict[str, Worker] = {}
        self.lock = threading.Lock()
        self.logger = logging.getLogger("Supervisor")
        self.stop_event = threading.Event()
        self.monitor_thread: threading.Thread = None

    def register_worker(self, name: str, run_fn: Callable[[], None], restart_on_fail: bool = True):
        """Registers a runner callback to be managed by the supervisor."""
        with self.lock:
            self.workers[name] = Worker(name, run_fn, restart_on_fail)
            self.logger.info(f"Worker '{name}' registered.")

    def start_worker(self, name: str):
        """Starts a registered worker thread."""
        with self.lock:
            worker = self.workers.get(name)
            if not worker:
                return

            if worker.thread and worker.thread.is_alive():
                self.logger.warning(f"Worker '{name}' is already running.")
                return

            worker.active = True
            worker.thread = threading.Thread(target=self._run_wrapper, args=(worker,), name=f"Worker-{name}", daemon=True)
            worker.thread.start()
            self.logger.info(f"Worker '{name}' started.")

    def _run_wrapper(self, worker: Worker):
        """Monitors and executes the actual worker function."""
        try:
            worker.run_fn()
        except Exception as e:
            self.logger.error(f"Worker '{worker.name}' crashed: {e}")
        finally:
            worker.active = False
            self.logger.info(f"Worker '{worker.name}' terminated.")

    def record_heartbeat(self, name: str):
        """Called by workers to signal they are responsive."""
        with self.lock:
            worker = self.workers.get(name)
            if worker:
                worker.last_heartbeat = time.time()

    def start_monitoring(self):
        """Launches the supervisor monitoring loop."""
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("Supervisor monitoring thread started.")

    def _monitor_loop(self):
        """Periodically audits worker health and restarts crashed worker targets."""
        while not self.stop_event.is_set():
            time.sleep(3)  # Audit interval
            with self.lock:
                for name, worker in list(self.workers.items()):
                    # Verify thread is alive or check heatbeat window
                    now = time.time()
                    is_thread_dead = worker.thread is None or not worker.thread.is_alive()
                    is_stale = (now - worker.last_heartbeat) > 30.0 # 30s heartbeat timeout

                    if worker.active and (is_thread_dead or is_stale):
                        self.logger.warning(f"Supervisor Alert: Worker '{name}' appears dead or stale (Thread Alive: {not is_thread_dead}, Age: {now - worker.last_heartbeat:.1f}s).")
                        if worker.restart_on_fail:
                            self.logger.info(f"Supervisor: Restarting worker '{name}'...")
                            worker.failures_count += 1
                            # Safeguard against infinite fast crash loops
                            if worker.failures_count > 5:
                                self.logger.error(f"Supervisor: Worker '{name}' failed too many times. Disabling auto-restart.")
                                worker.active = False
                                continue

                            # Re-trigger startup
                            worker.active = True
                            worker.last_heartbeat = time.time()
                            worker.thread = threading.Thread(target=self._run_wrapper, args=(worker,), name=f"Worker-{name}", daemon=True)
                            worker.thread.start()

    def cleanup_zombies(self):
        """Cleans up stray Chrome/Playwright/Python subprocesses during shutdown.

        IMPORTANT: Only processes spawned inside OUR descendant process tree are
        killed. This prevents nuking another user's unrelated Chrome/Playwright
        instances that happened to be running on the machine.
        """
        self.logger.info("Supervisor: Commencing zombie process cleanup...")
        current_pid = os.getpid()
        try:
            # Build the set of PIDs that belong to our own child tree (recursive).
            descendant_pids = set()
            try:
                me = psutil.Process(current_pid)
                for child in me.children(recursive=True):
                    descendant_pids.add(child.pid)
            except psutil.NoSuchProcess:
                pass

            if not descendant_pids:
                self.logger.info("Supervisor: No descendant processes to clean up.")
                return

            for proc in psutil.process_iter(['name', 'pid', 'cmdline']):
                try:
                    pname = proc.info['name'].lower()
                    if ("playwright" in pname or "chrome" in pname) and proc.pid in descendant_pids:
                        proc.kill()
                        self.logger.info(f"Supervisor: Killed descendant zombie '{proc.info['name']}' (pid {proc.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            self.logger.error(f"Error during zombie cleanup: {e}")

    def shutdown(self):
        """Performs a coordinated graceful shutdown of all supervised layers."""
        self.logger.info("Supervisor shutting down all workers...")
        self.stop_event.set()
        with self.lock:
            for _name, worker in self.workers.items():
                worker.active = False

        self.cleanup_zombies()
        self.logger.info("Supervisor shutdown complete.")

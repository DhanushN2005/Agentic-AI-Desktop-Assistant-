"""Vision mode: launch / stop the hand-gesture orb UI that lives in ``<project>/vision``.

The orb is a separate Next.js app. This module only starts and stops its dev server and reports
progress; it never runs anything but the fixed commands below, in the fixed folder.
"""
from __future__ import annotations

import atexit
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_log = logging.getLogger("Flexie.VisionMode")
START_PORT = 3000
READY_TIMEOUT = 90.0          # seconds to wait for the dev server to answer
INSTALL_TIMEOUT = 600.0       # first-time dependency install


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _free_port(start: int = START_PORT) -> int:
    for port in range(start, start + 20):
        if not _port_open(port):
            return port
    raise RuntimeError("no free local port between 3000 and 3019")


class VisionMode:
    def __init__(self, app_dir: str | None = None):
        self.app_dir = app_dir or os.path.join(_PROJECT_ROOT, "vision")
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self._lock = threading.Lock()
        self._busy = False
        atexit.register(self.stop)  # never leave the dev server running after Flexie exits

    # ------------------------------------------------------------ state
    @property
    def url(self) -> str | None:
        return f"http://localhost:{self.port}" if self.port else None

    def is_running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None and self.port and _port_open(self.port))

    def is_busy(self) -> bool:
        return self._busy

    def problem(self) -> str | None:
        """Why vision mode cannot start here (None = it can)."""
        if not os.path.isfile(os.path.join(self.app_dir, "package.json")):
            return f"The vision app folder is missing at {self.app_dir}."
        if not shutil.which("npm"):
            return "Node.js and npm are not installed, and vision mode needs them. Install Node.js, then ask again."
        return None

    def needs_install(self) -> bool:
        return not os.path.isdir(os.path.join(self.app_dir, "node_modules", "next"))

    # ------------------------------------------------------------ actions
    def _run(self, argv: list[str], timeout: float) -> tuple[bool, str]:
        try:
            r = subprocess.run(argv, cwd=self.app_dir, capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, f"timed out after {int(timeout)} seconds"
        except OSError as e:
            return False, str(e)
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()[-400:]

    def install(self) -> tuple[bool, str]:
        """npm ci (uses the lockfile, so versions are exactly the ones shipped with the app)."""
        npm = shutil.which("npm")
        lock = os.path.isfile(os.path.join(self.app_dir, "package-lock.json"))
        return self._run([npm, "ci" if lock else "install", "--no-audit", "--no-fund"], INSTALL_TIMEOUT)

    def start(self, say=lambda msg: None) -> tuple[bool, str]:
        """Install if needed, start the dev server and wait until it answers. Returns (ok, message)."""
        with self._lock:
            if self._busy:
                return False, "Vision mode is already starting."
            self._busy = True
        try:
            if self.is_running():
                return True, self.url or ""
            why = self.problem()
            if why:
                return False, why
            if self.needs_install():
                say("Setting up vision mode for the first time. This downloads its packages and can take a few minutes.")
                ok, out = self.install()
                if not ok:
                    return False, f"Setting up vision mode failed: {out or 'unknown error'}"
            self.port = _free_port()
            npm = shutil.which("npm")
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            self.proc = subprocess.Popen(
                [npm, "run", "dev", "--", "-p", str(self.port)], cwd=self.app_dir, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            deadline = time.monotonic() + READY_TIMEOUT
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    return False, "The vision app stopped right after starting."
                if _port_open(self.port):
                    return True, self.url or ""
                time.sleep(0.5)
            self.stop()
            return False, "The vision app did not come up in time."
        finally:
            self._busy = False

    def stop(self) -> bool:
        """Stop the dev server this object started (whole process tree)."""
        proc, self.proc = self.proc, None
        port, self.port = self.port, None
        if proc is None or proc.poll() is not None:
            return False
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
            else:
                proc.terminate()
        except (OSError, subprocess.SubprocessError) as e:
            _log.warning("vision mode stop failed (port %s): %s", port, e)
            return False
        return True

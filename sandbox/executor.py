import logging
import os
import subprocess
import sys
import threading
import time

IMAGE = "python:3.10-alpine"
MIN_TIMEOUT = 1
MAX_TIMEOUT = 120
_MAX_LOG_CHARS = 64_000

_client_lock = threading.Lock()
_client_cache = None  # one docker client per process (creating one costs a ping round-trip)


def _shared_docker_client():
    """Return the process-wide docker client, or None when Docker is unavailable."""
    global _client_cache
    with _client_lock:
        if _client_cache is not None:
            return _client_cache
        import docker  # may raise ImportError
        client = docker.from_env()
        client.ping()
        _client_cache = client
        return client


def _clamp_timeout(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 15
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, v))


class SandboxExecutor:
    """Executes code scripts inside isolated environments (Docker containers or resource-restricted sub-processes).

    SECURITY: By default (allow_host_fallback=False) execution is REFUSED when an
    isolated Docker sandbox is unavailable — the executor never silently runs
    untrusted code directly on the host. Callers that deliberately want host
    subprocess execution must opt in explicitly via allow_host_fallback=True.

    The ``*_ex`` methods return a structured ``(ok, output)`` pair; the legacy string methods
    wrap them and keep their historic message formats.
    """
    def __init__(self, timeout: int = 15, mem_limit: str = "256m", allow_host_fallback: bool = False):
        self.timeout = _clamp_timeout(timeout)
        self.mem_limit = mem_limit
        self.allow_host_fallback = allow_host_fallback
        self.logger = logging.getLogger("SandboxExecutor")
        self.docker_client = None
        self._init_docker()

    def _init_docker(self):
        try:
            self.docker_client = _shared_docker_client()
            self.logger.info("Docker daemon verified. Sandboxed containerization active.")
        except Exception as e:
            self.logger.warning(f"Docker initialization failed: {e}. Sandbox unavailable.")
            self.docker_client = None

    # ------------------------------------------------------------------ public API
    def run_python_code_ex(self, code: str) -> tuple[bool, str]:
        """Executes a raw python block inside the sandbox. Returns ``(ok, output)``."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="flexie_sandbox_") as tmpdir:
            temp_file = os.path.join(tmpdir, "script.py")
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(code)
            try:  # the container runs as 'nobody': the mount must be readable
                os.chmod(tmpdir, 0o755)
                os.chmod(temp_file, 0o644)
            except OSError as _e:
                logging.debug("[sandbox] chmod skipped: %s", _e)
            return self.run_python_script_ex(temp_file)

    def run_python_code(self, code: str) -> str:
        return self.run_python_code_ex(code)[1]

    def run_python_script(self, script_path: str) -> str:
        """Executes an existing script file inside the isolated sandbox."""
        return self.run_python_script_ex(script_path)[1]

    def _deny(self, reason: str) -> str:
        return (
            f"Sandbox execution refused: {reason}. No isolated Docker sandbox is "
            "available and host execution is disabled (allow_host_fallback=False)."
        )

    # ------------------------------------------------------------------ implementation
    def _image_missing(self) -> str | None:
        """Clear error when the image is not local (a pull would block for minutes)."""
        images = getattr(self.docker_client, "images", None)
        if images is None:
            return None
        try:
            images.get(IMAGE)
            return None
        except Exception as e:
            if type(e).__name__ == "ImageNotFound":
                return (f"Docker image '{IMAGE}' is not present locally. Pre-pull it once with "
                        f"`docker pull {IMAGE}` (the sandbox never pulls images on demand).")
            return None  # unknown error: let the run attempt report it

    def run_python_script_ex(self, script_path: str) -> tuple[bool, str]:
        abs_path = os.path.abspath(script_path)
        if not os.path.exists(abs_path):
            return False, f"Error: Script path {script_path} does not exist."

        if self.docker_client:
            container = None
            try:
                missing = self._image_missing()
                if missing:
                    return False, f"Sandbox execution refused: {missing}"
                script_dir = os.path.dirname(abs_path)
                script_file = os.path.basename(abs_path)
                self.logger.info(f"Sandbox: Executing {script_file} in Python container...")

                container = self.docker_client.containers.run(
                    image=IMAGE,
                    command=["python", "-B", f"/sandbox/{script_file}"],
                    volumes={script_dir: {"bind": "/sandbox", "mode": "ro"}},
                    working_dir="/tmp",
                    mem_limit=self.mem_limit,
                    memswap_limit=self.mem_limit,  # no swap on top of the memory cap
                    nano_cpus=1_000_000_000,       # at most one CPU
                    pids_limit=64,                 # fork-bomb guard
                    network_disabled=True,
                    read_only=True,
                    tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges"],
                    user="nobody",
                    environment={"PYTHONDONTWRITEBYTECODE": "1"},
                    detach=True,
                )

                start_time = time.time()
                while container.status == "created" or container.status == "running":
                    if time.time() - start_time > self.timeout:
                        return False, f"Execution Error: Code exceeded timeout threshold of {self.timeout} seconds."
                    time.sleep(0.2)
                    container.reload()

                logs = container.logs().decode("utf-8", errors="replace")
                if len(logs) > _MAX_LOG_CHARS:
                    logs = "...[truncated]...\n" + logs[-_MAX_LOG_CHARS:]
                exit_code = container.wait().get("StatusCode", 1)
                if exit_code != 0:
                    return False, f"Execution Failure (Exit Code {exit_code}):\n{logs}"
                return True, logs
            except Exception as de:
                self.logger.error(f"Docker run failed: {de}.")
                if not self.allow_host_fallback:
                    return False, self._deny(f"Docker run failed: {de}")
            finally:
                if container is not None:
                    # ALWAYS stop and remove it, whatever happened above.
                    try:
                        container.kill()
                    except Exception as _e:
                        logging.debug("[sandbox] kill skipped: %s", _e)
                    try:
                        container.remove()
                    except Exception as _e:
                        logging.debug("[sandbox] remove failed: %s", _e)

        # No Docker sandbox available — refuse unless the caller opted in.
        if not self.allow_host_fallback:
            return False, self._deny("Docker daemon not available")

        # Explicitly enabled host subprocess execution
        self.logger.warning("Sandbox: Running script on host subprocess (allow_host_fallback enabled).")
        try:
            proc = subprocess.run(
                [sys.executable, abs_path],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            if proc.returncode != 0:
                return False, f"Execution Failure (Exit Code {proc.returncode}):\n{proc.stderr}"
            return True, proc.stdout
        except subprocess.TimeoutExpired as _e:
            logging.debug("[sandbox/executor.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return False, f"Execution Error: Code exceeded timeout threshold of {self.timeout} seconds on host."
        except Exception as e:
            logging.debug("[sandbox/executor.py] Swallowed exception: %s: %s", type(e).__name__, e)
            return False, f"Host execution crash: {e}"

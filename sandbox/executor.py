import os
import subprocess
import logging
import time
from typing import Dict, Any

class SandboxExecutor:
    """Executes code scripts inside isolated environments (Docker containers or resource-restricted sub-processes).

    SECURITY: By default (allow_host_fallback=False) execution is REFUSED when an
    isolated Docker sandbox is unavailable — the executor never silently runs
    untrusted code directly on the host. Callers that deliberately want host
    subprocess execution must opt in explicitly via allow_host_fallback=True.
    """
    def __init__(self, timeout: int = 15, mem_limit: str = "256m", allow_host_fallback: bool = False):
        self.timeout = timeout
        self.mem_limit = mem_limit
        self.allow_host_fallback = allow_host_fallback
        self.logger = logging.getLogger("SandboxExecutor")
        self.docker_client = None
        self._init_docker()

    def _init_docker(self):
        try:
            import docker
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            self.logger.info("Docker daemon verified. Sandboxed containerization active.")
        except Exception as e:
            self.logger.warning(f"Docker initialization failed: {e}. Sandbox unavailable.")
            self.docker_client = None

    def run_python_code(self, code: str) -> str:
        """Executes a raw python block inside the sandbox environment."""
        # Save temp file
        temp_file = f"temp_code_{int(time.time())}.py"
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            res = self.run_python_script(temp_file)
            return res
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def _deny(self, reason: str) -> str:
        return (
            f"Sandbox execution refused: {reason}. No isolated Docker sandbox is "
            "available and host execution is disabled (allow_host_fallback=False)."
        )

    def run_python_script(self, script_path: str) -> str:
        """Executes an existing script file inside the isolated sandbox."""
        abs_path = os.path.abspath(script_path)
        if not os.path.exists(abs_path):
            return f"Error: Script path {script_path} does not exist."

        if self.docker_client:
            try:
                # Docker execution path
                # Mount script directory as volume and run container
                script_dir = os.path.dirname(abs_path)
                script_file = os.path.basename(abs_path)

                self.logger.info(f"Sandbox: Executing {script_file} in Python container containerized...")

                # Run container (using official python alpine image)
                container = self.docker_client.containers.run(
                    image="python:3.10-alpine",
                    command=f"python /sandbox/{script_file}",
                    volumes={script_dir: {"bind": "/sandbox", "mode": "ro"}},
                    mem_limit=self.mem_limit,
                    network_disabled=True,  # Disable network access for safety
                    detach=True
                )

                # Check for completion with timeout limits
                start_time = time.time()
                while container.status == "created" or container.status == "running":
                    if time.time() - start_time > self.timeout:
                        container.kill()
                        container.remove()
                        return f"Execution Error: Code exceeded timeout threshold of {self.timeout} seconds."
                    time.sleep(0.2)
                    container.reload()

                logs = container.logs().decode("utf-8")
                exit_code = container.wait().get("StatusCode", 1)
                container.remove()

                if exit_code != 0:
                    return f"Execution Failure (Exit Code {exit_code}):\n{logs}"
                return logs
            except Exception as de:
                self.logger.error(f"Docker run failed: {de}.")
                if not self.allow_host_fallback:
                    return self._deny(f"Docker run failed: {de}")

        # No Docker sandbox available — refuse unless the caller opted in.
        if not self.allow_host_fallback:
            return self._deny("Docker daemon not available")

        # Explicitly enabled host subprocess execution
        self.logger.warning("Sandbox: Running script on host subprocess (allow_host_fallback enabled).")
        try:
            # Run python process with timeout
            proc = subprocess.run(
                ["python", abs_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout
            )
            if proc.returncode != 0:
                return f"Execution Failure (Exit Code {proc.returncode}):\n{proc.stderr}"
            return proc.stdout
        except subprocess.TimeoutExpired:
            return f"Execution Error: Code exceeded timeout threshold of {self.timeout} seconds on host."
        except Exception as e:
            return f"Host execution crash: {e}"

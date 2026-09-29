"""Verification and Self-Healing Engine for Build Jobs.

Features:
- Stack detection (Python, Node.js, Rust, Java, Static HTML).
- Per-project isolated environment (.venv for Python, npm install --no-audit for Node).
- Execution sequence: install -> lint -> tests -> start app.
- Dynamic port allocation, readiness polling, smoke testing, and process tree teardown.
- Self-heal loop: up to 3 attempts, error signature duplicate detection, syntax-checked patching.
- Real acceptance criteria verification updating ACCEPTANCE.md.
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from core.jobs.generator import strip_fences_and_prose, validate_syntax
from core.jobs.process import kill_process_tree
from utils.path_jail import resolve_in_root

logger = logging.getLogger("flexie.jobs.verifier")


def detect_stack(workspace_path: str) -> str:
    """Detect primary language/runtime stack from workspace configuration files."""
    if os.path.exists(os.path.join(workspace_path, "package.json")):
        return "node"
    if (
        os.path.exists(os.path.join(workspace_path, "requirements.txt"))
        or os.path.exists(os.path.join(workspace_path, "pyproject.toml"))
        or any(f.endswith(".py") for f in os.listdir(workspace_path) if os.path.isfile(os.path.join(workspace_path, f)))
    ):
        return "python"
    if os.path.exists(os.path.join(workspace_path, "Cargo.toml")):
        return "rust"
    if os.path.exists(os.path.join(workspace_path, "pom.xml")):
        return "java"
    if os.path.exists(os.path.join(workspace_path, "index.html")):
        return "static"
    return "unknown"


def find_free_port() -> int:
    """Dynamically allocate an available ephemeral localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return s.getsockname()[1]


def get_project_venv(workspace_path: str) -> Tuple[str, str]:
    """Get or create an isolated per-project virtualenv. NEVER pollutes global Python."""
    venv_dir = os.path.join(workspace_path, ".venv")
    if sys.platform == "win32":
        py_exe = os.path.join(venv_dir, "Scripts", "python.exe")
        pip_exe = os.path.join(venv_dir, "Scripts", "pip.exe")
    else:
        py_exe = os.path.join(venv_dir, "bin", "python")
        pip_exe = os.path.join(venv_dir, "bin", "pip")

    if not os.path.exists(py_exe):
        logger.info("Creating isolated virtualenv in %s...", venv_dir)
        try:
            res = subprocess.run(
                [sys.executable, "-m", "venv", ".venv"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            if res.returncode != 0:
                logger.warning("Failed creating venv: %s. Falling back to host python.", res.stderr)
                return sys.executable, sys.executable
        except Exception as e:
            logger.warning("venv creation exception: %s", e)
            return sys.executable, sys.executable

    return py_exe, pip_exe


def install_dependencies(workspace_path: str, stack: str) -> Tuple[bool, str]:
    """Install dependencies into isolated project environment."""
    if stack == "python":
        req_file = os.path.join(workspace_path, "requirements.txt")
        if not os.path.exists(req_file):
            return True, "No requirements.txt found; skipping install."

        py_exe, pip_exe = get_project_venv(workspace_path)
        logger.info("Installing Python dependencies into project .venv via %s...", pip_exe)
        try:
            res = subprocess.run(
                [pip_exe, "install", "-r", "requirements.txt"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
            )
            if res.returncode == 0:
                return True, "Dependencies installed successfully."
            return False, f"pip install failed:\n{res.stderr.strip()}"
        except Exception as e:
            return False, f"pip install exception: {e}"

    elif stack == "node":
        pkg_file = os.path.join(workspace_path, "package.json")
        if not os.path.exists(pkg_file):
            return True, "No package.json found; skipping install."

        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        if not shutil.which(npm_cmd):
            return False, "Node.js npm executable not found on PATH."

        try:
            res = subprocess.run(
                [npm_cmd, "install", "--no-audit", "--no-fund"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=180,
                shell=False,
            )
            if res.returncode == 0:
                return True, "npm dependencies installed successfully."
            return False, f"npm install failed:\n{res.stderr.strip()}"
        except Exception as e:
            return False, f"npm install exception: {e}"

    return True, "No package installation required."


def run_tests(workspace_path: str, stack: str) -> Tuple[bool, str]:
    """Execute automated unit/integration tests in the isolated project environment."""
    if stack == "python":
        py_exe, _ = get_project_venv(workspace_path)
        test_files = [f for f in os.listdir(workspace_path) if f.startswith("test_") and f.endswith(".py")]
        if not test_files and not os.path.exists(os.path.join(workspace_path, "tests")):
            return True, "No Python test files found."

        try:
            res = subprocess.run(
                [py_exe, "-m", "pytest", "-q"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            if res.returncode == 0:
                return True, f"Pytest passed:\n{res.stdout.strip()}"
            return False, f"Pytest failed:\n{res.stdout}\n{res.stderr}".strip()
        except Exception as e:
            return False, f"Pytest execution error: {e}"

    elif stack == "node":
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            res = subprocess.run(
                [npm_cmd, "test", "--if-present"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
            )
            if res.returncode == 0:
                return True, "npm test passed."
            return False, f"npm test failed:\n{res.stderr.strip()}"
        except Exception as e:
            return False, f"npm test execution error: {e}"

    return True, "No tests to run."


def start_and_smoke_test(
    workspace_path: str,
    stack: str,
    run_command: str,
    port: int,
    max_wait_seconds: float = 8.0,
) -> Tuple[bool, str]:
    """Launch the application on a dynamic port, poll for readiness, smoke test, and tear down."""
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["FLASK_RUN_PORT"] = str(port)

    # Command normalization to respect isolated venv
    cmd_parts = run_command.strip().split()
    if not cmd_parts:
        return False, "Empty run command."

    if stack == "python":
        py_exe, _ = get_project_venv(workspace_path)
        if cmd_parts[0] in ("python", "python3", "py"):
            cmd_parts[0] = py_exe

    # If static site with http.server, ensure port argument is set
    if "http.server" in run_command and not any(p.isdigit() for p in cmd_parts[2:]):
        cmd_parts.append(str(port))

    # Resolve executable on Windows if needed
    if sys.platform == "win32" and cmd_parts[0].lower().endswith((".cmd", ".bat")):
        cmd_parts = ["cmd.exe", "/c"] + cmd_parts

    proc = None
    try:
        logger.info("Launching server for smoke test: %s (PORT=%d)", " ".join(cmd_parts), port)
        proc = subprocess.Popen(
            cmd_parts,
            cwd=workspace_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )

        # Readiness polling loop (no fixed sleeps)
        start_time = time.monotonic()
        ready = False
        target_urls = [
            f"http://127.0.0.1:{port}",
            f"http://127.0.0.1:{port}/health",
            f"http://localhost:{port}",
        ]

        while time.monotonic() - start_time < max_wait_seconds:
            # Check if process died early
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=1)
                return False, f"Server process exited prematurely (code {proc.returncode}):\n{err or out}".strip()

            for url in target_urls:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "FlexieVerifier/2.0"})
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        if resp.status < 400:
                            ready = True
                            logger.info("Readiness poll verified at %s (HTTP %d)", url, resp.status)
                            break
                except Exception:
                    pass

            if ready:
                break
            time.sleep(0.3)

        if not ready:
            return False, f"Server did not become ready within {max_wait_seconds}s on port {port}."

        return True, f"Application successfully started and passed smoke test on port {port}."

    except Exception as e:
        return False, f"Error launching application: {e}"
    finally:
        if proc is not None:
            try:
                kill_process_tree(proc.pid)
            except Exception as te:
                logger.debug("Error tearing down dev server: %s", te)


class SelfHealer:
    """Performs up to 3 self-healing iterations with duplicate error signature guards."""

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self.error_signatures: List[str] = []

    def compute_signature(self, error_text: str) -> str:
        """Hash the error text ignoring memory addresses and line numbers for duplicate detection."""
        normalized = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", error_text)
        normalized = re.sub(r"line \d+", "line N", normalized)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]

    def attempt_heal(
        self,
        workspace_path: str,
        error_output: str,
        relevant_file: str,
        brain: Any,
        plan_summary: str = "",
    ) -> Tuple[bool, str]:
        """Attempt to repair a broken file using LLM and syntax validation.

        Returns (success: bool, explanation: str).
        """
        # Guard: check duplicate error signature
        sig = self.compute_signature(error_output)
        if self.error_signatures.count(sig) >= 1:
            msg = f"Self-heal stopped early: identical error signature {sig} encountered again."
            logger.warning(msg)
            return False, msg
        self.error_signatures.append(sig)

        if len(self.error_signatures) > self.max_attempts:
            msg = f"Exceeded maximum self-heal attempts ({self.max_attempts})."
            logger.warning(msg)
            return False, msg

        # Read relevant file
        try:
            target_path = resolve_in_root(relevant_file, workspace_path)
            if not os.path.exists(target_path):
                return False, f"Target file for repair does not exist: {relevant_file}"
            with open(target_path, "r", encoding="utf-8") as f:
                current_code = f.read()
        except Exception as e:
            return False, f"Cannot access file for repair: {e}"

        truncated_error = "\n".join(error_output.strip().splitlines()[-50:])

        test_context = ""
        for test_candidate in ("tests/test_app.py", "test_app.py", "tests/test_main.py", "test_main.py"):
            t_path = os.path.join(workspace_path, test_candidate)
            if os.path.isfile(t_path):
                try:
                    with open(t_path, "r", encoding="utf-8") as tf:
                        test_context = f"\n\nTest Suite Requirements ({test_candidate}):\n{tf.read()[:2500]}"
                        break
                except Exception:
                    pass

        prompt = f"""You are an automated code repair expert.
Project Plan: {plan_summary}
File to fix: {relevant_file}

Recent Error / Traceback:
{truncated_error}
{test_context}

Current File Content:
{current_code[:3000]}

Fix the issue in {relevant_file} so all tests pass. Return ONLY the complete, corrected source code inside a single code block.
Do not provide conversational prose.
"""
        try:
            repaired_raw = brain.ask(
                prompt,
                system_override="You are a code repair bot. Return ONLY valid, complete source code in a markdown block.",
                use_rag=False,
            )
            repaired_code = strip_fences_and_prose(relevant_file, repaired_raw or "")
            ok, syntax_err = validate_syntax(relevant_file, repaired_code)
            if not ok:
                return False, f"Repaired code contains syntax error: {syntax_err}"

            with open(target_path, "w", encoding="utf-8") as f:
                f.write(repaired_code)
            logger.info("Applied self-heal patch to %s (attempt %d)", relevant_file, len(self.error_signatures))
            return True, f"Applied fix to {relevant_file}"
        except Exception as e:
            return False, f"Self-heal exception: {e}"


def verify_and_update_acceptance(workspace_path: str, passed_criteria: List[str]) -> bool:
    """Update ACCEPTANCE.md with verified checkmarks [x]."""
    acc_path = os.path.join(workspace_path, "ACCEPTANCE.md")
    if not os.path.exists(acc_path):
        return True

    try:
        with open(acc_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.strip().startswith("- [ ]"):
                item_text = line.strip()[5:].strip().lower()
                # Check if any passed criterion matches this item
                if any(p.lower() in item_text or item_text in p.lower() for p in passed_criteria):
                    updated_lines.append(line.replace("- [ ]", "- [x]"))
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)

        with open(acc_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
        return True
    except Exception as e:
        logger.warning("Could not update ACCEPTANCE.md: %s", e)
        return False

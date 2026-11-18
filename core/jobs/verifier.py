"""Verification and Self-Healing Engine for Build Jobs.

Features:
- Stack detection (Python, Node.js, Rust, Java, Static HTML).
- Per-project isolated environment (.venv for Python, npm install --no-audit for Node).
  Never falls back to the host interpreter; requirements.txt is vetted before pip sees it.
- Every subprocess runs with a scrubbed environment, is registered with the job's
  ProcessTracker, is cancellable, and is killed as a whole process tree on timeout.
- Dynamic port allocation, readiness polling, smoke testing, and process tree teardown.
- Self-heal loop: bounded attempts, duplicate error-signature detection, syntax-checked,
  backed-up, revertible patching that never rewrites a file from a truncated view.
- Real acceptance criteria verification updating ACCEPTANCE.md.
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from core.jobs.generator import neutralize_secrets, strip_fences_and_prose, validate_syntax
from core.jobs.planner import PlanValidationError, parse_run_command
from core.jobs.process import (
    job_cancelled,
    kill_process_tree,
    release_tracked,
    run_tracked,
    scrubbed_env,
    spawn_tracked,
)
from core.jobs.safe_paths import (
    SKIP_DIRS,
    atomic_write,
    find_by_basename,
    prune_dirs,
    rel_inside,
    safe_join,
)
from utils.config import Config
from utils.path_jail import resolve_in_root

logger = logging.getLogger("flexie.jobs.verifier")

# Localhost probe address — intentionally not configurable (always loopback)
_LOOPBACK = "127.0.0.1"

MAX_HEAL_FILE_CHARS = 20_000
MAX_REQUIREMENTS = 100


class VenvError(RuntimeError):
    """The isolated project virtualenv could not be created."""


def detect_stack(workspace_path: str) -> str:
    """Detect primary language/runtime stack from workspace configuration files."""
    if os.path.exists(os.path.join(workspace_path, "package.json")):
        return "node"
    try:
        root_files = [f for f in os.listdir(workspace_path) if os.path.isfile(os.path.join(workspace_path, f))]
    except OSError:
        root_files = []
    if (
        os.path.exists(os.path.join(workspace_path, "requirements.txt"))
        or os.path.exists(os.path.join(workspace_path, "pyproject.toml"))
        or any(f.endswith(".py") for f in root_files)
    ):
        return "python"
    if os.path.exists(os.path.join(workspace_path, "Cargo.toml")):
        return "rust"
    if os.path.exists(os.path.join(workspace_path, "pom.xml")):
        return "java"
    if os.path.exists(os.path.join(workspace_path, "index.html")):
        return "static"
    plan_md = os.path.join(workspace_path, "PLAN.md")
    if os.path.exists(plan_md):
        try:
            with open(plan_md, encoding="utf-8") as _f:
                _content = _f.read()
            if "static-web" in _content or "static_web" in _content:
                return "static"
        except Exception as _e:
            logger.debug("PLAN.md unreadable: %s", _e)
    return "unknown"


# ---------------------------------------------------------- failing-file lookup
def is_test_file(rel: str) -> bool:
    norm = rel.replace("\\", "/").lower()
    base = os.path.basename(norm)
    parts = norm.split("/")
    return (
        base.startswith("test_")
        or base.endswith(("_test.py", ".test.js", ".spec.js", ".test.jsx", ".spec.jsx", ".test.ts", ".spec.ts"))
        or base == "conftest.py"
        or "tests" in parts[:-1]
        or "__tests__" in parts[:-1]
    )


def _candidate_to_rel(cand: str, workspace_path: str) -> str | None:
    """Map a path found in error output to a source file inside the workspace, or None."""
    if not cand or not isinstance(cand, str):
        return None
    norm = cand.replace("\\", "/")
    parts = {p.lower() for p in norm.split("/")}
    if parts & SKIP_DIRS or "site-packages" in norm.lower() or ".." in parts:
        return None
    absolute = os.path.isabs(cand) or norm.startswith("/") or bool(re.match(r"^[A-Za-z]:", cand))
    rel = rel_inside(cand, workspace_path)
    if rel or absolute:
        return rel  # absolute paths outside the workspace (even other drives) are never used
    return find_by_basename(workspace_path, os.path.basename(norm))


def extract_failing_file(error_output: str, workspace_path: str) -> str:
    """Parse error output / tracebacks to find the most likely broken source file.

    Only files inside the workspace source tree are returned (never .venv,
    node_modules, site-packages, other drives or parent directories). Non-test
    sources are preferred over tests. Returns a relative path string.
    """
    text = error_output if isinstance(error_output, str) else ""
    test_candidate: str | None = None

    def consider(cand: str) -> str | None:
        nonlocal test_candidate
        rel = _candidate_to_rel(cand, workspace_path)
        if not rel:
            return None
        if is_test_file(rel):
            test_candidate = test_candidate or rel
            return None
        return rel

    # 1. Python traceback frames (last frame is usually the root cause)
    for cand in reversed(re.findall(r'File ["\']([^"\']+\.py)["\']', text)):
        rel = consider(cand)
        if rel:
            return rel

    # 1b. pytest short-form "path.py:LINE:" frames
    for cand in reversed(re.findall(r"([\w./\\:-]+\.py):\d+", text)):
        rel = consider(cand)
        if rel:
            return rel

    # 2. Node/Vite/npm errors
    node_matches = re.findall(
        r'(?:ERROR|error|FAILED|failed)[^\n]*?([\w./\\:-]+\.(?:js|jsx|ts|tsx|mjs|cjs))(?::\d+)?',
        text,
    )
    for cand in node_matches:
        rel = consider(cand)
        if rel:
            return rel

    # 3. pytest FAILED lines (usually test files; remembered as a last resort)
    for cand in re.findall(r"FAILED\s+([\w./\\-]+\.py)", text):
        consider(cand)

    # 4. Most recently modified non-test source file in the source tree
    exts = (".py", ".js", ".jsx", ".ts", ".tsx")
    latest_file: str | None = None
    latest_mtime = 0.0
    for root, dirs, files in os.walk(workspace_path):
        prune_dirs(dirs)
        for fname in files:
            if fname.endswith(exts):
                full = os.path.join(root, fname)
                try:
                    rel = os.path.relpath(full, workspace_path)
                    mtime = os.path.getmtime(full)
                except (OSError, ValueError):
                    continue
                if not is_test_file(rel) and mtime > latest_mtime:
                    latest_mtime, latest_file = mtime, rel
    if latest_file:
        return latest_file
    if test_candidate:
        return test_candidate

    for name in ("app.py", "main.py", "index.js", "src/App.jsx"):
        if os.path.exists(os.path.join(workspace_path, name)):
            return name
    return "app.py"


def find_free_port() -> int:
    """Dynamically allocate an available ephemeral localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_LOOPBACK, 0))
        s.listen(1)
        return s.getsockname()[1]


# ------------------------------------------------------------------- venv / pip
def get_project_venv(workspace_path: str) -> tuple[str, str]:
    """Get or create an isolated per-project virtualenv.

    Raises VenvError on failure — it NEVER falls back to the host interpreter, so
    nothing from a build job can be installed into Flexie's own environment.
    """
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
            res = run_tracked(
                [sys.executable, "-m", "venv", ".venv"],
                cwd=workspace_path,
                timeout=getattr(Config, "JOB_VENV_TIMEOUT", 60),
            )
        except Exception as e:
            raise VenvError(f"Could not create the project virtualenv: {e}") from e
        if res.timed_out:
            raise VenvError("Creating the project virtualenv timed out.")
        if res.cancelled:
            raise VenvError("Cancelled while creating the project virtualenv.")
        if res.returncode != 0 or not os.path.exists(py_exe):
            raise VenvError(f"Could not create the project virtualenv: {(res.stderr or res.stdout).strip()[:400]}")
    return py_exe, pip_exe


_REQ_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_REQ_SPEC = r"(?:===|==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9.*+!_-]+"
_REQ_LINE = re.compile(
    rf"^{_REQ_NAME}(?:\[[A-Za-z0-9,._-]+\])?\s*(?:{_REQ_SPEC}(?:\s*,\s*{_REQ_SPEC})*)?\s*(?:;\s*[A-Za-z0-9 .,'\"<>=!~_()-]+)?$"
)


def vet_requirements(text: str) -> tuple[list[str], list[str]]:
    """Return ``(clean_lines, problems)`` for an LLM-written requirements.txt.

    Rejects pip options (-r, -e, --index-url, ...), URLs, VCS refs, local paths,
    direct references (``pkg @ url``), malformed names, and caps the count.
    """
    clean: list[str] = []
    problems: list[str] = []
    for raw in (text or "").splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        if line.startswith("-"):
            problems.append(f"pip option not allowed: {line[:80]}")
        elif "://" in line or "@" in line or line.lower().startswith(("git+", "hg+", "svn+", "bzr+", "file:")):
            problems.append(f"URL / VCS / direct reference not allowed: {line[:80]}")
        elif any(ch in line for ch in "\\/") or line.startswith((".", "~")):
            problems.append(f"local path not allowed: {line[:80]}")
        elif not _REQ_LINE.match(line):
            problems.append(f"invalid requirement syntax: {line[:80]}")
        else:
            clean.append(line)
    if len(clean) > MAX_REQUIREMENTS:
        problems.append(f"too many requirements ({len(clean)} > {MAX_REQUIREMENTS})")
    return clean, problems


def _pip_env() -> dict[str, str]:
    return scrubbed_env({"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1", "PYTHONUNBUFFERED": "1"})


def _npm_exe() -> str | None:
    return shutil.which("npm.cmd" if sys.platform == "win32" else "npm")


def install_dependencies(workspace_path: str, stack: str) -> tuple[bool, str]:
    """Install dependencies into isolated project environment."""
    if stack in ("static", "static-web", "unknown"):
        return True, "Static web project — no dependencies to install."

    if stack == "python":
        try:
            py_exe, _ = get_project_venv(workspace_path)
        except VenvError as e:
            return False, str(e)
        logger.info("Installing Python dependencies into project .venv via %s -m pip...", py_exe)
        pip_cmd = [py_exe, "-m", "pip"]
        install_timeout = getattr(Config, "JOB_INSTALL_TIMEOUT", 180)

        try:
            res_pytest = run_tracked(
                [*pip_cmd, "install", "pytest", "pytest-cov", "--quiet"],
                cwd=workspace_path,
                timeout=install_timeout // 2,
                env=_pip_env(),
            )
            if res_pytest.cancelled:
                return False, "Cancelled."
            if res_pytest.returncode != 0:
                logger.warning("pytest pre-install failed: %s", res_pytest.stderr.strip()[:300])
        except Exception as _pe:
            logger.warning("pytest pre-install exception: %s", _pe)

        req_file = os.path.join(workspace_path, "requirements.txt")
        if not os.path.exists(req_file):
            return True, "No requirements.txt found; pytest installed."

        try:
            with open(req_file, encoding="utf-8", errors="replace") as f:
                req_text = f.read(256 * 1024)
        except OSError as e:
            return False, f"Cannot read requirements.txt: {e}"
        clean, problems = vet_requirements(req_text)
        if problems:
            return False, "requirements.txt rejected:\n" + "\n".join(problems[:10])
        if not clean:
            return True, "requirements.txt is empty; pytest installed."

        fd, vetted = tempfile.mkstemp(suffix=".txt", prefix="flexie_req_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(clean) + "\n")
            res = run_tracked(
                [*pip_cmd, "install", "-r", vetted],
                cwd=workspace_path,
                timeout=install_timeout,
                env=_pip_env(),
            )
        except Exception as e:
            return False, f"pip install exception: {e}"
        finally:
            with contextlib.suppress(OSError):
                os.remove(vetted)
        if res.cancelled:
            return False, "Cancelled."
        if res.timed_out:
            return False, f"pip install timed out after {install_timeout}s."
        if res.returncode == 0:
            return True, "Dependencies installed successfully."
        return False, f"pip install failed:\n{res.stderr.strip()}"

    elif stack == "node":
        pkg_file = os.path.join(workspace_path, "package.json")
        if not os.path.exists(pkg_file):
            return True, "No package.json found; skipping install."

        npm = _npm_exe()
        if not npm:
            return False, "Node.js npm executable not found on PATH."
        timeout = getattr(Config, "JOB_INSTALL_TIMEOUT", 180)
        try:
            res = run_tracked([npm, "install", "--no-audit", "--no-fund"], cwd=workspace_path, timeout=timeout)
        except Exception as e:
            return False, f"npm install exception: {e}"
        if res.cancelled:
            return False, "Cancelled."
        if res.timed_out:
            return False, f"npm install timed out after {timeout}s."
        if res.returncode == 0:
            return True, "npm dependencies installed successfully."
        return False, f"npm install failed:\n{res.stderr.strip()}"

    return True, "No package installation required."


def run_build_check(workspace_path: str, stack: str) -> tuple[bool, str]:
    """Run a compile/build step instead of a live HTTP smoke test."""
    npm = _npm_exe()
    if not npm:
        return False, "npm not found on PATH. Cannot run build check."

    install_ok, install_msg = install_dependencies(workspace_path, stack)
    if not install_ok:
        return False, f"Dependency install failed before build: {install_msg}"

    build_timeout = getattr(Config, "JOB_BUILD_TIMEOUT", 120)
    try:
        res = run_tracked([npm, "run", "build"], cwd=workspace_path, timeout=build_timeout)
    except Exception as e:
        return False, f"Build check exception: {e}"
    if res.cancelled:
        return False, "Cancelled."
    if res.timed_out:
        return False, f"npm run build timed out after {build_timeout} seconds."
    if res.returncode == 0:
        return True, f"npm run build succeeded.\n{res.stdout.strip()[:500]}"
    return False, f"npm run build failed (exit {res.returncode}):\n{(res.stderr or res.stdout).strip()[:800]}"


def run_tests(workspace_path: str, stack: str) -> tuple[bool, str]:
    """Execute automated unit/integration tests in the isolated project environment."""
    if stack in ("static", "static-web", "unknown"):
        index_html = os.path.join(workspace_path, "index.html")
        if os.path.exists(index_html) and os.path.getsize(index_html) > 0:
            return True, "Static web project verified: index.html exists and is non-empty."
        for sub in ("dist", "build", "public"):
            sub_html = os.path.join(workspace_path, sub, "index.html")
            if os.path.exists(sub_html):
                return True, f"Static web project verified: {sub}/index.html exists."
        return False, "Static web project is missing index.html."

    timeout = getattr(Config, "JOB_TEST_TIMEOUT", 60)
    if stack == "python":
        try:
            py_exe, _ = get_project_venv(workspace_path)
        except VenvError as e:
            return False, str(e)
        test_files = [f for f in os.listdir(workspace_path) if f.startswith("test_") and f.endswith(".py")]
        if not test_files and not os.path.exists(os.path.join(workspace_path, "tests")):
            return True, "No Python test files found."
        try:
            res = run_tracked(
                [py_exe, "-m", "pytest", "-q"],
                cwd=workspace_path,
                timeout=timeout,
                env=scrubbed_env({"PYTHONUNBUFFERED": "1"}),
            )
        except Exception as e:
            return False, f"Pytest execution error: {e}"
        if res.cancelled:
            return False, "Cancelled."
        if res.timed_out:
            return False, f"Pytest timed out after {timeout}s."
        if res.returncode == 0:
            return True, f"Pytest passed:\n{res.stdout.strip()}"
        return False, f"Pytest failed:\n{res.stdout}\n{res.stderr}".strip()

    elif stack == "node":
        npm = _npm_exe()
        if not npm:
            return False, "Node.js npm executable not found on PATH."
        try:
            res = run_tracked([npm, "test", "--if-present"], cwd=workspace_path, timeout=timeout)
        except Exception as e:
            return False, f"npm test execution error: {e}"
        if res.cancelled:
            return False, "Cancelled."
        if res.timed_out:
            return False, f"npm test timed out after {timeout}s."
        if res.returncode == 0:
            return True, "npm test passed."
        return False, f"npm test failed:\n{res.stderr.strip() or res.stdout.strip()}"

    return True, "No tests to run."


# ---------------------------------------------------------------- smoke test
@dataclass
class SmokeResult:
    ok: bool
    message: str
    mode: str = "fail"  # "http" | "exited_ok" | "fail"
    port: int = 0
    matched_url: str | None = None
    warning: str | None = None


_PYTHON_LAUNCHERS = {"python", "python3", "py"}
_PY_MODULE_LAUNCHERS = {"flask", "uvicorn", "gunicorn", "streamlit"}
_ADDR_IN_USE = re.compile(r"address already in use|eaddrinuse|only one usage of each socket|winerror 10048|winerror 10013|forbidden by its access permissions|errno 98|errno 10048", re.I)


def _interpreter_for(stack: str, workspace_path: str) -> str:
    if stack == "python":
        return get_project_venv(workspace_path)[0]  # may raise VenvError
    return sys.executable


def _has_flag(args: list[str], *flags: str) -> bool:
    return any(a == f or a.startswith(f + "=") for a in args for f in flags)


def build_run_argv(workspace_path: str, stack: str, run_command: str, port: int) -> list[str]:
    """Turn a validated run command into an argv that honours ``port`` and uses the venv.

    No shell and no cmd.exe wrapper: executables are resolved to full paths, so
    spaces in program or project paths need no quoting rules.
    """
    parts = parse_run_command(run_command)
    if not parts:
        raise ValueError("Empty run command.")
    name = parts[0].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    rest = parts[1:]

    if name in _PYTHON_LAUNCHERS:
        exe = _interpreter_for(stack, workspace_path)
        if "http.server" in rest:
            idx = rest.index("http.server")
            tail = [a for a in rest[idx + 1:] if not a.isdigit()]
            if not _has_flag(tail, "--bind", "-b"):
                tail += ["--bind", _LOOPBACK]
            return [exe, *rest[: idx + 1], str(port), *tail]
        return [exe, *rest]

    if name in _PY_MODULE_LAUNCHERS:
        exe = _interpreter_for(stack, workspace_path)
        args = list(rest)
        if name == "flask" and "run" in args:
            if not _has_flag(args, "--port", "-p"):
                args += ["--port", str(port)]
            if not _has_flag(args, "--host", "-h"):
                args += ["--host", _LOOPBACK]
        elif name == "uvicorn":
            if not _has_flag(args, "--port"):
                args += ["--port", str(port)]
            if not _has_flag(args, "--host"):
                args += ["--host", _LOOPBACK]
        elif name == "gunicorn" and not _has_flag(args, "-b", "--bind"):
            args += ["-b", f"{_LOOPBACK}:{port}"]
        return [exe, "-m", name, *args]

    candidates = [name + ".cmd", name] if sys.platform == "win32" else [name]
    resolved = next((p for p in (shutil.which(c) for c in candidates) if p), None)
    if not resolved:
        raise FileNotFoundError(f"'{name}' was not found on PATH.")
    args = list(rest)
    if name == "vite":
        if not _has_flag(args, "--port"):
            args += ["--port", str(port), "--strictPort"]
        if not _has_flag(args, "--host"):
            args += ["--host", _LOOPBACK]
    return [resolved, *args]


_PORT_IN_OUTPUT = re.compile(r"(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1?\]|\*):(\d{2,5})", re.I)


def _listening_ports(pid: int) -> set[int]:
    ports: set[int] = set()
    try:
        import psutil

        proc = psutil.Process(pid)
        for p in [proc, *proc.children(recursive=True)]:
            getter = getattr(p, "net_connections", None) or getattr(p, "connections", None)
            if getter is None:
                continue
            for c in getter(kind="inet"):
                if c.status == psutil.CONN_LISTEN and c.laddr:
                    ports.add(int(c.laddr.port))
    except Exception as e:
        logger.debug("listening-port detection unavailable: %s", e)
    return ports


def _probe(port: int) -> str | None:
    for url in (f"http://{_LOOPBACK}:{port}", f"http://{_LOOPBACK}:{port}/health", f"http://localhost:{port}"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FlexieVerifier/2.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status < 400:
                    return url
        except Exception as _e:
            logger.debug("probe %s failed: %s", url, _e)
    return None


def _read_back(f) -> str:
    try:
        f.flush()
        f.seek(0)
        return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _smoke_once(workspace_path: str, argv: list[str], port: int, max_wait: float) -> tuple[SmokeResult, bool]:
    """One launch attempt. Returns (result, retry_with_new_port)."""
    env = scrubbed_env(
        {
            "PORT": str(port),
            "FLASK_RUN_PORT": str(port),
            "FLASK_DEBUG": "0",
            "HOST": _LOOPBACK,
            "PYTHONUNBUFFERED": "1",
        }
    )
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    proc = None
    try:
        logger.info("Launching server for smoke test: %s (PORT=%d)", " ".join(argv), port)
        proc = spawn_tracked(argv, cwd=workspace_path, env=env, stdout=out_f, stderr=err_f)
        start = time.monotonic()
        tried_other: set[int] = set()
        while time.monotonic() - start < max_wait:
            if job_cancelled():
                return SmokeResult(False, "Cancelled during smoke test.", "fail", port), False
            rc = proc.poll()
            if rc is not None:
                output = (_read_back(err_f) + "\n" + _read_back(out_f)).strip()
                # A server may have bound just before exiting; one last probe.
                if rc == 0:
                    return SmokeResult(
                        True,
                        f"Process ran to completion with exit code 0 (command-style app).\n{output[-300:]}".strip(),
                        "exited_ok",
                        port,
                    ), False
                if _ADDR_IN_USE.search(output):
                    return SmokeResult(False, f"Port {port} was already in use.\n{output[-300:]}", "fail", port), True
                return SmokeResult(
                    False, f"Server process exited prematurely (code {rc}):\n{output[-1500:]}", "fail", port
                ), False

            url = _probe(port)
            if url:
                return SmokeResult(
                    True, f"Application successfully started and passed smoke test on port {port}.",
                    "http", port, url,
                ), False

            # The app may ignore PORT and bind a hardcoded port: detect and probe it.
            if time.monotonic() - start > 1.5:
                seen = _listening_ports(proc.pid)
                text = _read_back(err_f) + "\n" + _read_back(out_f)
                seen |= {int(m) for m in _PORT_IN_OUTPUT.findall(text) if 0 < int(m) < 65536}
                for other in sorted(seen - {port} - tried_other):
                    url = _probe(other)
                    if url:
                        return SmokeResult(
                            True,
                            f"Application started but bound port {other} instead of the requested {port}.",
                            "http", other, url,
                            warning=f"Hardcoded port {other}: the app ignores the PORT environment variable.",
                        ), False
                    if time.monotonic() - start > max_wait * 0.8:
                        tried_other.add(other)
            time.sleep(0.3)

        output = (_read_back(err_f) + "\n" + _read_back(out_f)).strip()
        return SmokeResult(
            False,
            f"Server did not become ready within {max_wait}s on port {port}."
            + (f"\nOutput:\n{output[-800:]}" if output else ""),
            "fail", port,
        ), False
    except Exception as e:
        return SmokeResult(False, f"Error launching application: {e}", "fail", port), False
    finally:
        if proc is not None:
            try:
                kill_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5)
            except Exception as te:
                logger.debug("Error tearing down dev server: %s", te)
            release_tracked(proc)
        for f in (out_f, err_f):
            with contextlib.suppress(Exception):
                f.close()


def start_and_smoke_test_ex(
    workspace_path: str,
    stack: str,
    run_command: str,
    port: int,
    max_wait_seconds: float = -1.0,
) -> SmokeResult:
    """Launch the app on ``port``, poll for readiness, smoke test, and tear down."""
    if max_wait_seconds < 0:
        max_wait_seconds = getattr(Config, "JOB_SMOKE_WAIT", 12.0)
    result = SmokeResult(False, "Smoke test did not run.", "fail", port)
    for attempt in range(3):
        try:
            argv = build_run_argv(workspace_path, stack, run_command, port)
        except (PlanValidationError, ValueError, FileNotFoundError, VenvError) as e:
            return SmokeResult(False, f"Cannot start application: {e}", "fail", port)
        result, retry = _smoke_once(workspace_path, argv, port, max_wait_seconds)
        if not retry:
            return result
        logger.info("Smoke test port %d collided (attempt %d); picking a new port.", port, attempt + 1)
        port = find_free_port()
    return result


def start_and_smoke_test(
    workspace_path: str,
    stack: str,
    run_command: str,
    port: int,
    max_wait_seconds: float = -1.0,
) -> tuple[bool, str]:
    """Tuple-returning wrapper around :func:`start_and_smoke_test_ex`."""
    res = start_and_smoke_test_ex(workspace_path, stack, run_command, port, max_wait_seconds)
    msg = res.message if not res.warning else f"{res.message} WARNING: {res.warning}"
    return res.ok, msg


# ---------------------------------------------------------------- self healing
_PLACEHOLDER_REPLY = re.compile(
    r"rest of (the )?(file|code)|(previous|existing) (code|implementation) (here|remains|unchanged)"
    r"|\.\.\.\s*\(?(omitted|truncated|same|unchanged)",
    re.I,
)


def _count_tests(code: str) -> tuple[int, int]:
    return len(re.findall(r"\bassert\b|\bexpect\(|\.should\.", code)), len(re.findall(r"\bdef test_|\b(?:it|test)\(", code))


class SelfHealer:
    """Performs bounded self-healing iterations with duplicate error signature guards."""

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts
        self.error_signatures: list[str] = []
        self._backups: list[tuple[str, str]] = []  # (absolute path, original text)

    def compute_signature(self, error_text: str) -> str:
        """Hash the error text ignoring memory addresses and line numbers for duplicate detection."""
        normalized = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", error_text)
        normalized = re.sub(r"line \d+", "line N", normalized)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]

    def revert_all(self) -> int:
        """Restore every file this healer modified (newest first). Returns files restored."""
        n = 0
        for path, original in reversed(self._backups):
            try:
                atomic_write(path, original)
                n += 1
            except OSError as e:
                logger.error("Could not revert %s: %s", path, e)
        self._backups.clear()
        return n

    def _save_backup(self, workspace_path: str, rel: str, original: str) -> None:
        try:
            bdir = os.path.join(workspace_path, ".flexie_backups")
            os.makedirs(bdir, exist_ok=True)
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", rel)
            atomic_write(os.path.join(bdir, f"{int(time.time())}_{len(self._backups)}_{name}"), original)
        except OSError as e:
            logger.debug("Could not write backup copy: %s", e)

    def attempt_heal(
        self,
        workspace_path: str,
        error_output: str,
        relevant_file: str,
        brain: Any,
        plan_summary: str = "",
    ) -> tuple[bool, str]:
        """Attempt to repair a broken file using LLM and validation. Returns (success, explanation)."""
        error_output = error_output if isinstance(error_output, str) else str(error_output or "")
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

        try:
            target_path = safe_join(workspace_path, relevant_file)
            target_path = resolve_in_root(target_path, workspace_path)
            rel = os.path.relpath(target_path, os.path.realpath(workspace_path))
            parts = {p.lower() for p in re.split(r"[\\/]+", rel)}
            if parts & SKIP_DIRS or "site-packages" in rel.lower():
                return False, f"Refusing to modify dependency/VCS file: {relevant_file}"
            if not os.path.exists(target_path):
                return False, f"Target file for repair does not exist: {relevant_file}"
            with open(target_path, encoding="utf-8") as f:
                current_code = f.read()
        except Exception as e:
            return False, f"Cannot access file for repair: {e}"

        base = os.path.basename(rel)
        if is_test_file(rel):
            broken_itself = re.search(
                r"error collecting|SyntaxError|IndentationError|ImportError while importing test module", error_output
            ) and base in error_output
            if not broken_itself:
                return False, f"Refusing to rewrite test file {relevant_file}: tests are the spec, fix the code under test."

        if len(current_code) > MAX_HEAL_FILE_CHARS:
            return False, (
                f"{relevant_file} is too large ({len(current_code)} chars) to rewrite safely from a single reply."
            )

        truncated_error = "\n".join(error_output.strip().splitlines()[-50:])

        test_context = ""
        for test_candidate in ("tests/test_app.py", "test_app.py", "tests/test_main.py", "test_main.py"):
            t_path = os.path.join(workspace_path, test_candidate)
            if os.path.isfile(t_path):
                try:
                    with open(t_path, encoding="utf-8") as tf:
                        test_context = f"\n\nTest Suite Requirements ({test_candidate}):\n{tf.read()[:2500]}"
                        break
                except Exception as _e:
                    logger.debug("test context unreadable: %s", _e)

        prompt = f"""You are an automated code repair expert.
Project Plan: {plan_summary}
File to fix: {relevant_file}

Recent Error / Traceback:
{truncated_error}
{test_context}

Current File Content (complete):
{current_code}

Fix the issue in {relevant_file} so all tests pass. Do not weaken or delete tests/assertions. Return ONLY the complete, corrected source code inside a single code block.
Do not provide conversational prose.
"""
        try:
            repaired_raw = brain.ask(
                prompt,
                system_override="You are a code repair bot. Return ONLY valid, complete source code in a markdown block.",
                use_rag=False,
            )
            repaired_code = strip_fences_and_prose(relevant_file, repaired_raw if isinstance(repaired_raw, str) else "")
            repaired_code, _ = neutralize_secrets(repaired_code, workspace_path, relevant_file)
            ok, syntax_err = validate_syntax(relevant_file, repaired_code)
            if not ok:
                return False, f"Repaired code contains syntax error: {syntax_err}"
            if len(current_code) > 200 and len(repaired_code) < 0.5 * len(current_code):
                return False, "Repaired code is drastically shorter than the original; rejecting as incomplete."
            if _PLACEHOLDER_REPLY.search(repaired_code) and not _PLACEHOLDER_REPLY.search(current_code):
                return False, "Repaired code contains placeholders instead of a complete file."
            if is_test_file(rel):
                old_a, old_t = _count_tests(current_code)
                new_a, new_t = _count_tests(repaired_code)
                if new_a < old_a or new_t < old_t:
                    return False, "Refusing to weaken tests (fewer assertions/tests in the repaired file)."

            self._save_backup(workspace_path, rel, current_code)
            self._backups.append((target_path, current_code))
            try:
                atomic_write(target_path, repaired_code)
            except OSError as we:
                self._backups.pop()
                return False, f"Could not write repaired file: {we}"
            logger.info("Applied self-heal patch to %s (attempt %d)", relevant_file, len(self.error_signatures))
            return True, f"Applied fix to {relevant_file}"
        except Exception as e:
            return False, f"Self-heal exception: {e}"


def verify_and_update_acceptance(workspace_path: str, passed_criteria: list[str]) -> bool:
    """Update ACCEPTANCE.md with verified checkmarks [x] (only for criteria actually verified)."""
    acc_path = os.path.join(workspace_path, "ACCEPTANCE.md")
    if not os.path.exists(acc_path):
        return True

    passed = [p.lower() for p in passed_criteria if isinstance(p, str) and p.strip()]
    try:
        with open(acc_path, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.strip().startswith("- [ ]"):
                item_text = line.strip()[5:].strip().lower()
                if item_text and any(p in item_text or item_text in p for p in passed):
                    updated_lines.append(line.replace("- [ ]", "- [x]", 1))
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)

        atomic_write(acc_path, "".join(updated_lines))
        return True
    except Exception as e:
        logger.warning("Could not update ACCEPTANCE.md: %s", e)
        return False

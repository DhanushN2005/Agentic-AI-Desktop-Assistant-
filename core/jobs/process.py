"""Process tree management, scrubbed environments and cancellable subprocess runs."""
from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

logger = logging.getLogger("flexie.jobs.process")

_IS_WIN = sys.platform == "win32"


# --------------------------------------------------------------------------- env
_ALLOW_EXACT = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "ALLUSERSPROFILE", "PUBLIC",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS",
    "USERNAME", "USERDOMAIN", "COMPUTERNAME", "LANG", "LANGUAGE", "TZ", "TERM", "SHELL",
    "USER", "LOGNAME", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "ALL_PROXY", "CI", "DISPLAY", "XDG_RUNTIME_DIR",
}
_ALLOW_PREFIX = ("PYTHON", "NODE", "NPM_CONFIG_", "LC_")
_DENY_EXACT = {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONSTARTUP", "NODE_PATH"}
_SECRET_NAME = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASS|CREDENTIAL|AUTH|COOKIE|SESSION)", re.IGNORECASE
)
_PROVIDER_NAME = re.compile(
    r"^(GROQ|OPENAI|ANTHROPIC|GEMINI|GOOGLE|AWS|AZURE|HF|HUGGINGFACE|ELEVENLABS|DEEPGRAM|"
    r"MISTRAL|COHERE|TOGETHER|OPENROUTER|XAI|PERPLEXITY|FLEXIE|GITHUB|GH|GITLAB|SLACK|"
    r"TWILIO|STRIPE|SENDGRID|NPM_TOKEN|PIP_)",
    re.IGNORECASE,
)


def scrubbed_env(extra: dict[str, str] | None = None, base: dict[str, str] | None = None) -> dict[str, str]:
    """Build a child-process environment from an allowlist with secrets removed.

    Anything not on the allowlist is dropped; anything whose *name* looks like a
    credential, or belongs to a known provider, is dropped even when allowlisted
    by prefix (e.g. ``npm_config__authToken``). ``extra`` is applied last.
    """
    src = os.environ if base is None else base
    out: dict[str, str] = {}
    for name, value in src.items():
        up = name.upper()
        if up in _DENY_EXACT:
            continue
        allowed = up in _ALLOW_EXACT or up.startswith(_ALLOW_PREFIX)
        if not allowed:
            continue
        if up not in ("PATH", "PATHEXT", "COMSPEC") and (_SECRET_NAME.search(up) or _PROVIDER_NAME.match(up)):
            continue
        if up.endswith("_PROXY") and "@" in (value or ""):
            continue  # proxy URL with embedded credentials
        out[name] = value
    if extra:
        for k, v in extra.items():
            out[str(k)] = str(v)
    return out


# ----------------------------------------------------------------- kill helpers
def kill_process_tree(pid: int) -> bool:
    """Terminate a process and all of its spawned children cleanly without crashing."""
    if not isinstance(pid, int) or pid <= 0:
        return False

    if _IS_WIN:
        try:
            res = subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
                env=scrubbed_env(),
            )
            if res.returncode == 0:
                logger.info("Process tree for PID %s killed via taskkill", pid)
                return True
        except Exception as e:
            logger.debug("taskkill failed for PID %s: %s", pid, e)

    try:
        import psutil
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            with contextlib.suppress(Exception):
                child.kill()
        parent.kill()
        logger.info("Process tree for PID %s killed via psutil", pid)
        return True
    except Exception as pe:
        logger.debug("psutil tree kill failed for PID %s: %s", pid, pe)

    try:
        import signal
        if not _IS_WIN:
            with contextlib.suppress(Exception):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception as _e:
        logger.debug("os.kill fallback failed for PID %s: %s", pid, _e)
    return False


class ProcessTracker:
    """Thread-safe registry of running subprocesses tied to jobs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._procs: dict[str, list[subprocess.Popen]] = {}

    def register(self, job_id: str, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.setdefault(job_id, []).append(proc)

    def unregister(self, job_id: str, proc: subprocess.Popen) -> None:
        with self._lock:
            lst = self._procs.get(job_id)
            if lst and proc in lst:
                lst.remove(proc)
                if not lst:
                    self._procs.pop(job_id, None)

    def count(self, job_id: str) -> int:
        with self._lock:
            return len(self._procs.get(job_id, []))

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


# ------------------------------------------------------------- job context (TLS)
_ctx = threading.local()


@contextlib.contextmanager
def job_context(job_id: str | None, tracker: ProcessTracker | None, cancel_event: threading.Event | None) -> Iterator[None]:
    """Bind the current thread to a job so every subprocess is tracked/cancellable."""
    prev = getattr(_ctx, "value", None)
    _ctx.value = (job_id, tracker, cancel_event)
    try:
        yield
    finally:
        _ctx.value = prev


def current_job_context() -> tuple[str | None, ProcessTracker | None, threading.Event | None]:
    return getattr(_ctx, "value", None) or (None, None, None)


def job_cancelled() -> bool:
    """True when the job bound to the current thread has been cancelled or paused."""
    _, _, ev = current_job_context()
    return bool(ev is not None and ev.is_set())


# ------------------------------------------------------------------- running
@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


def _popen_flags() -> dict:
    if _IS_WIN:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def _read_tail(f, limit: int = 2_000_000) -> str:
    try:
        f.flush()
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - limit))
        return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def spawn_tracked(
    argv: Sequence[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    stdout=None,
    stderr=None,
) -> subprocess.Popen:
    """Popen (never a shell) in its own process group, registered with the bound job."""
    job_id, tracker, _ = current_job_context()
    proc = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=env if env is not None else scrubbed_env(),
        stdin=subprocess.DEVNULL,
        stdout=stdout if stdout is not None else subprocess.DEVNULL,
        stderr=stderr if stderr is not None else subprocess.DEVNULL,
        shell=False,
        **_popen_flags(),
    )
    if tracker is not None and job_id:
        tracker.register(job_id, proc)
    return proc


def release_tracked(proc: subprocess.Popen) -> None:
    job_id, tracker, _ = current_job_context()
    if tracker is not None and job_id:
        tracker.unregister(job_id, proc)


def run_tracked(
    argv: Sequence[str],
    *,
    cwd: str,
    timeout: float,
    env: dict[str, str] | None = None,
    poll: float = 0.1,
) -> RunResult:
    """Run ``argv`` with a scrubbed env, bounded time and cooperative cancellation.

    Output goes to temp files (no pipes), so a grandchild that inherits the handles
    can never block us; on timeout/cancel the whole process TREE is killed.
    """
    _, _, cancel = current_job_context()
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = spawn_tracked(argv, cwd=cwd, env=env, stdout=out_f, stderr=err_f)
        timed_out = cancelled = False
        deadline = time.monotonic() + max(0.1, float(timeout))
        try:
            while True:
                try:
                    proc.wait(timeout=poll)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
            if timed_out or cancelled:
                kill_process_tree(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(Exception):
                        proc.kill()
        finally:
            release_tracked(proc)
        rc = proc.returncode if proc.returncode is not None else -1
        return RunResult(rc, _read_tail(out_f), _read_tail(err_f), timed_out, cancelled)

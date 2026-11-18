"""Git versioning and phase undo operations inside job workspaces."""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import time
from dataclasses import dataclass

from core.jobs.process import RunResult, run_tracked, scrubbed_env
from utils.config import Config
from utils.path_jail import resolve_in_root

logger = logging.getLogger("flexie.jobs.git")

_GIT_WARNED = False
_STALE_LOCK_SECONDS = 120

GITIGNORE_LINES = [
    ".venv/", "venv/", "env/", "node_modules/", "__pycache__/", "*.pyc", ".pytest_cache/",
    ".mypy_cache/", ".ruff_cache/", ".env", ".env.local", ".vscode/settings.json",
    ".flexie_build.log", ".flexie_backups/", "*.part", ".flexie_tmp_*",
]


def _timeout() -> int:
    return int(getattr(Config, "JOB_GIT_TIMEOUT", 60))


def is_git_available() -> bool:
    global _GIT_WARNED
    has_git = bool(shutil.which("git"))
    if not has_git and not _GIT_WARNED:
        logger.warning("Git CLI is not installed or not on PATH. Phase versioning & undo disabled.")
        _GIT_WARNED = True
    return has_git


_MUTATING = {"add", "commit", "reset", "checkout", "config", "clean", "restore", "rm", "stash", "switch", "merge", "rebase"}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path)).rstrip("/\\")


def owns_repo(workspace: str) -> bool:
    """True only if git's toplevel for ``workspace`` IS the workspace (its own repo).

    Without this, a workspace lacking its own ``.git`` resolves to a PARENT repository
    and ``git add -A`` / ``commit`` / ``reset`` would act on the parent's work tree.
    """
    if not isinstance(workspace, str) or not workspace.strip():
        return False  # '' would resolve to the process cwd (possibly an unrelated repo)
    real_ws = os.path.realpath(workspace)
    if not os.path.isdir(real_ws):
        return False
    try:
        res = run_tracked(
            ["git", "rev-parse", "--show-toplevel"], cwd=real_ws, timeout=15,
            env=scrubbed_env({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}),
        )
    except Exception as e:
        logger.warning("git toplevel check failed in %s: %s", real_ws, e)
        return False
    top = res.stdout.strip()
    return res.returncode == 0 and bool(top) and _norm(top) == _norm(real_ws)


def _subcommand(args: list[str]) -> str:
    i = 0
    while i < len(args):
        if args[i] == "-c":
            i += 2
            continue
        return args[i]
    return ""


def _git(args: list[str], cwd: str, timeout: float | None = None) -> RunResult:
    """Run git (no shell, scrubbed env, tree-killed on timeout).

    Mutating subcommands are refused unless ``cwd`` is the root of its own repository.
    """
    if _subcommand(args) in _MUTATING and not owns_repo(cwd):
        msg = f"refusing git {_subcommand(args)}: {cwd} is not the root of its own git repository"
        logger.error(msg)
        return RunResult(128, "", msg)
    env = scrubbed_env({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    return run_tracked(["git", *args], cwd=cwd, timeout=timeout or _timeout(), env=env)


def ensure_gitignore(workspace: str) -> bool:
    """Create/extend .gitignore so dependency dirs, secrets and build junk are never committed."""
    if not isinstance(workspace, str) or not workspace.strip():
        return False
    path = os.path.join(workspace, ".gitignore")
    existing: list[str] = []
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                existing = f.read().splitlines()
        have = {ln.strip() for ln in existing}
        missing = [ln for ln in GITIGNORE_LINES if ln not in have]
        if not missing and existing:
            return True
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(existing + (["# added by Flexie"] if existing else []) + missing) + "\n")
        return True
    except OSError as e:
        logger.warning("Could not write .gitignore in %s: %s", workspace, e)
        return False


def clean_stale_index_lock(real_ws: str, force: bool = False) -> bool:
    """Remove .git/index.lock when it is stale (older than 2 min) or ``force`` (our git was killed)."""
    lock = os.path.join(real_ws, ".git", "index.lock")
    try:
        if not os.path.exists(lock) or not owns_repo(real_ws):
            return False
        age = time.time() - os.path.getmtime(lock)
        if force or age >= _STALE_LOCK_SECONDS:
            os.remove(lock)
            logger.warning("Removed stale git index.lock in %s (age %.0fs)", real_ws, age)
            return True
    except OSError as e:
        logger.warning("Could not remove index.lock in %s: %s", real_ws, e)
    return False


def init_job_repo(workspace: str, workspace_root: str | None = None) -> bool:
    """Initialize a git repository in the job workspace if git is available."""
    if not is_git_available() or not isinstance(workspace, str) or not workspace.strip():
        return False

    real_ws = os.path.realpath(workspace)
    if workspace_root:
        try:
            resolve_in_root(real_ws, workspace_root)
        except Exception as e:
            logger.error("Git init refused: workspace escapes root: %s", e)
            return False

    ensure_gitignore(real_ws)
    git_dir = os.path.join(real_ws, ".git")
    if os.path.exists(git_dir):
        return owns_repo(real_ws)

    try:
        res = _git(["init"], real_ws, 30)  # creates the workspace's OWN repo (never touches a parent)
        if res.returncode != 0:
            logger.warning("git init failed in %s: %s", real_ws, res.stderr)
            return False
        if not owns_repo(real_ws):
            logger.error("git init in %s did not produce an own repository", real_ws)
            return False
        _git(["config", "user.name", getattr(Config, "GIT_USER_NAME", "Flexie Dev Assistant")], real_ws, 10)
        _git(["config", "user.email", getattr(Config, "GIT_USER_EMAIL", "flexie@local")], real_ws, 10)
        return True
    except Exception as e:
        logger.warning("git init error in %s: %s", real_ws, e)
        return False


@dataclass
class CommitResult:
    sha: str | None  # short sha of a commit created by THIS call, else None
    committed: bool
    error: str | None = None


def _head(real_ws: str) -> str | None:
    r = _git(["rev-parse", "HEAD"], real_ws, 15)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def commit_job_phase_ex(workspace: str, phase_name: str, message: str) -> CommitResult:
    """Stage and commit; reports whether a new commit was really made and any failure."""
    if not is_git_available():
        return CommitResult(None, False, "git not available")
    if not isinstance(workspace, str) or not workspace.strip():
        return CommitResult(None, False, "job has no workspace path; refusing to run git in the current directory")
    real_ws = os.path.realpath(workspace)
    if not os.path.exists(os.path.join(real_ws, ".git")):
        return CommitResult(None, False, "not a git repository")

    if not owns_repo(real_ws):
        return CommitResult(None, False, f"{real_ws} is not the root of its own git repository; refusing to commit")
    try:
        ensure_gitignore(real_ws)
        clean_stale_index_lock(real_ws)
        before = _head(real_ws)

        add = _git(["add", "-A"], real_ws)
        if add.timed_out:
            clean_stale_index_lock(real_ws, force=True)
            return CommitResult(None, False, f"git add timed out after {_timeout()}s")
        if add.returncode != 0:
            return CommitResult(None, False, f"git add failed: {add.stderr.strip()[:300]}")

        name = getattr(Config, "GIT_USER_NAME", "Flexie Dev Assistant")
        email = getattr(Config, "GIT_USER_EMAIL", "flexie@local")
        commit = _git(
            ["-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-m", f"phase({phase_name}): {message}"],
            real_ws,
        )
        if commit.timed_out:
            clean_stale_index_lock(real_ws, force=True)
            return CommitResult(None, False, f"git commit timed out after {_timeout()}s")

        after = _head(real_ws)
        if after and after != before:
            short = _git(["rev-parse", "--short", "HEAD"], real_ws, 15)
            return CommitResult(short.stdout.strip() or after[:7], True)
        out = f"{commit.stdout}\n{commit.stderr}".lower()
        if commit.returncode == 0 or "nothing to commit" in out or "nothing added" in out:
            return CommitResult(None, False)  # genuinely nothing to commit
        return CommitResult(None, False, f"git commit failed: {(commit.stderr or commit.stdout).strip()[:300]}")
    except Exception as e:
        logger.warning("git commit error in %s: %s", real_ws, e)
        return CommitResult(None, False, str(e))


def commit_job_phase(workspace: str, phase_name: str, message: str) -> str | None:
    """Commit and return the NEW commit's short SHA, or None when nothing was committed."""
    res = commit_job_phase_ex(workspace, phase_name, message)
    if res.error:
        logger.warning("Phase commit problem: %s", res.error)
    return res.sha


def undo_last_phase(
    workspace: str, workspace_root: str | None = None, expected_commit: str | None = None
) -> tuple[bool, str]:
    """Hard reset to the commit before the last phase commit.

    When ``expected_commit`` is given, HEAD must be exactly that commit, otherwise
    nothing is reset (prevents reverting two phases after a no-op phase).
    """
    if not is_git_available():
        return False, "Git is not available on this system. Undo is disabled."
    if not isinstance(workspace, str) or not workspace.strip():
        return False, "Job has no workspace path."

    real_ws = os.path.realpath(workspace)
    if workspace_root:
        try:
            resolve_in_root(real_ws, workspace_root)
        except Exception as e:
            return False, f"Workspace security check failed: {e}"

    if not os.path.exists(os.path.join(real_ws, ".git")):
        return False, "Workspace is not a git repository."

    if not owns_repo(real_ws):
        return False, "Workspace is not the root of its own git repository; refusing to roll back."
    try:
        clean_stale_index_lock(real_ws)
        if expected_commit:
            exp = _git(["rev-parse", "--verify", f"{expected_commit}^{{commit}}"], real_ws, 15)
            head = _head(real_ws)
            if exp.returncode != 0 or not head or exp.stdout.strip() != head:
                return False, "The workspace has moved on since that phase was committed; refusing to roll back."

        check = _git(["rev-parse", "--verify", "HEAD~1"], real_ws, 15)
        if check.returncode != 0:
            return False, "No previous phase commit found to roll back to."

        reset_res = _git(["reset", "--hard", "HEAD~1"], real_ws)
        if reset_res.timed_out:
            clean_stale_index_lock(real_ws, force=True)
            return False, "Git reset timed out."
        if reset_res.returncode == 0:
            return True, "Successfully rolled back workspace to previous phase commit."
        return False, f"Git reset failed: {reset_res.stderr.strip()}"
    except Exception as e:
        return False, f"Undo operation encountered an error: {e}"


def get_job_git_history(workspace: str, max_count: int = 10) -> list[dict]:
    """Return recent git commit log for the workspace."""
    if not is_git_available() or not isinstance(workspace, str) or not workspace.strip():
        return []

    real_ws = os.path.realpath(workspace)
    if not os.path.exists(os.path.join(real_ws, ".git")):
        return []

    with contextlib.suppress(Exception):
        res = _git(["log", f"-n{int(max_count)}", "--format=%h|%s"], real_ws, 15)
        if res.returncode != 0:
            return []
        commits = []
        for line in res.stdout.strip().splitlines():
            if "|" in line:
                sha, msg = line.split("|", 1)
                commits.append({"sha": sha.strip(), "message": msg.strip()})
        return commits
    return []

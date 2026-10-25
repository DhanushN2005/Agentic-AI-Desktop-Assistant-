"""Git versioning and phase undo operations inside job workspaces."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Optional, Tuple

from utils.config import Config
from utils.path_jail import resolve_in_root

logger = logging.getLogger("flexie.jobs.git")

_GIT_WARNED = False


def is_git_available() -> bool:
    global _GIT_WARNED
    has_git = bool(shutil.which("git"))
    if not has_git and not _GIT_WARNED:
        logger.warning("Git CLI is not installed or not on PATH. Phase versioning & undo disabled.")
        _GIT_WARNED = True
    return has_git


def init_job_repo(workspace: str, workspace_root: Optional[str] = None) -> bool:
    """Initialize a git repository in the job workspace if git is available."""
    if not is_git_available():
        return False

    real_ws = os.path.realpath(workspace)
    if workspace_root:
        try:
            resolve_in_root(real_ws, workspace_root)
        except Exception as e:
            logger.error("Git init refused: workspace escapes root: %s", e)
            return False

    git_dir = os.path.join(real_ws, ".git")
    if os.path.exists(git_dir):
        return True

    try:
        res = subprocess.run(
            ["git", "init"],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if res.returncode != 0:
            logger.warning("git init failed in %s: %s", real_ws, res.stderr)
            return False

        # Set identity if unconfigured locally
        subprocess.run(
            ["git", "config", "user.name", getattr(Config, "GIT_USER_NAME", "Flexie Dev Assistant")],
            cwd=real_ws,
            capture_output=True,
            timeout=5,
            shell=False,
        )
        subprocess.run(
            ["git", "config", "user.email", getattr(Config, "GIT_USER_EMAIL", "flexie@local")],
            cwd=real_ws,
            capture_output=True,
            timeout=5,
            shell=False,
        )
        return True
    except Exception as e:
        logger.warning("git init error in %s: %s", real_ws, e)
        return False


def commit_job_phase(workspace: str, phase_name: str, message: str) -> Optional[str]:
    """Stage all files and commit with a clear phase message. Returns commit SHA if made."""
    if not is_git_available():
        return None

    real_ws = os.path.realpath(workspace)
    if not os.path.exists(os.path.join(real_ws, ".git")):
        return None

    try:
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )

        # Commit
        commit_msg = f"phase({phase_name}): {message}"
        res = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )

        # If nothing to commit, return current HEAD
        rev_res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        if rev_res.returncode == 0:
            return rev_res.stdout.strip()
    except Exception as e:
        logger.warning("git commit error in %s: %s", real_ws, e)
    return None


def undo_last_phase(workspace: str, workspace_root: Optional[str] = None) -> Tuple[bool, str]:
    """Hard reset to the previous phase commit inside the job workspace."""
    if not is_git_available():
        return False, "Git is not available on this system. Undo is disabled."

    real_ws = os.path.realpath(workspace)
    if workspace_root:
        try:
            resolve_in_root(real_ws, workspace_root)
        except Exception as e:
            return False, f"Workspace security check failed: {e}"

    if not os.path.exists(os.path.join(real_ws, ".git")):
        return False, "Workspace is not a git repository."

    try:
        # Check if HEAD~1 exists
        check = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD~1"],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        if check.returncode != 0:
            return False, "No previous phase commit found to roll back to."

        # Perform hard reset
        reset_res = subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        if reset_res.returncode == 0:
            return True, "Successfully rolled back workspace to previous phase commit."
        return False, f"Git reset failed: {reset_res.stderr.strip()}"
    except Exception as e:
        return False, f"Undo operation encountered an error: {e}"


def get_job_git_history(workspace: str, max_count: int = 10) -> list[dict]:
    """Return recent git commit log for the workspace."""
    if not is_git_available():
        return []

    real_ws = os.path.realpath(workspace)
    if not os.path.exists(os.path.join(real_ws, ".git")):
        return []

    try:
        res = subprocess.run(
            ["git", "log", f"-n{max_count}", "--format=%h|%s"],
            cwd=real_ws,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        if res.returncode != 0:
            return []

        commits = []
        for line in res.stdout.strip().splitlines():
            if "|" in line:
                sha, msg = line.split("|", 1)
                commits.append({"sha": sha.strip(), "message": msg.strip()})
        return commits
    except Exception as e:
        logger.debug("Failed to read git history in %s: %s", real_ws, e)
        return []

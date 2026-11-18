"""Desktop and IDE launcher for background build jobs.

Provides safe, subprocess-based launching for VS Code, browser preview,
and desktop notifications without shell=True or blocking calls.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from typing import Any

from core.jobs.models import BuildJob
from core.jobs.process import scrubbed_env

logger = logging.getLogger("flexie.jobs.launcher")


def find_vscode_executable() -> str | None:
    """Find the VS Code executable on Windows safely."""
    # Check standard PATH first
    which_code = shutil.which("code")
    if which_code:
        return which_code

    # Check common Windows install locations
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")

    candidates = [
        os.path.join(local_app_data, "Programs", "Microsoft VS Code", "bin", "code.cmd"),
        os.path.join(local_app_data, "Programs", "Microsoft VS Code", "Code.exe"),
        os.path.join(program_files, "Microsoft VS Code", "bin", "code.cmd"),
        os.path.join(program_files, "Microsoft VS Code", "Code.exe"),
        os.path.join(program_files_x86, "Microsoft VS Code", "bin", "code.cmd"),
        os.path.join(program_files_x86, "Microsoft VS Code", "Code.exe"),
    ]

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate

    return None


def _vscode_argv(code_path: str, workspace_dir: str) -> list[str] | str:
    """Command for VS Code that survives spaces in BOTH the program and project paths.

    Preference order: the real ``Code.exe`` beside ``bin/code.cmd`` (no shell at all);
    a plain .cmd/.bat goes through ``cmd.exe /c`` - as an argv list when neither path
    has spaces, otherwise as the canonical ``cmd /d /s /c ""prog" "arg""`` string so
    cmd's quote-stripping rule cannot mangle the two quoted paths.
    """
    if not code_path.lower().endswith((".cmd", ".bat")):
        return [code_path, workspace_dir]
    exe = os.path.join(os.path.dirname(os.path.dirname(code_path)), "Code.exe")
    if os.path.isfile(exe):
        return [exe, workspace_dir]
    if " " not in code_path and " " not in workspace_dir:
        return ["cmd.exe", "/c", code_path, workspace_dir]
    if any(ch in code_path + workspace_dir for ch in '"%&^|<>!'):
        raise ValueError("unsafe characters in VS Code or workspace path")
    return f'cmd.exe /d /s /c ""{code_path}" "{workspace_dir}""'


def open_folder(path: str) -> tuple[bool, str]:
    """Open a folder in the platform file manager. Never raises; returns (ok, message)."""
    if not path or not os.path.isdir(path):
        return False, f"The folder no longer exists: {path or '(none)'}"
    try:
        if sys.platform == "win32" and hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
            return True, "opened"
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        exe = shutil.which(opener)
        if exe:
            subprocess.Popen(
                [exe, path], shell=False, env=scrubbed_env(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True, "opened"
        if webbrowser.open("file:///" + os.path.abspath(path).replace(os.sep, "/")):
            return True, "opened"
        return False, "No file manager is available to open the folder."
    except (OSError, AttributeError, ValueError) as e:
        logger.warning("Could not open folder %s: %s", path, e)
        return False, f"Could not open the folder: {e}"


def launch_in_vscode(workspace_dir: str) -> bool:
    """Open workspace_dir in VS Code, falling back to the file manager."""
    if not os.path.isdir(workspace_dir):
        logger.error("Cannot launch VS Code: workspace directory '%s' does not exist", workspace_dir)
        return False

    code_path = find_vscode_executable()
    if code_path:
        try:
            subprocess.Popen(
                _vscode_argv(code_path, workspace_dir),
                shell=False,
                env=scrubbed_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Launched VS Code for %s using %s", workspace_dir, code_path)
            return True
        except Exception as e:
            logger.warning("Failed to launch VS Code via executable '%s': %s", code_path, e)

    ok, msg = open_folder(workspace_dir)
    if not ok:
        logger.error("Fallback folder open failed for '%s': %s", workspace_dir, msg)
    return ok


def open_in_browser(target: str) -> bool:
    """Open a URL or HTML file in the default system browser."""
    try:
        if os.path.isfile(target):
            url = f"file:///{os.path.abspath(target).replace(os.sep, '/')}"
        else:
            url = target

        webbrowser.open(url)
        logger.info("Opened in browser: %s", url)
        return True
    except Exception as e:
        logger.error("Browser launch failed for '%s': %s", target, e)
        return False


def find_browser_target(workspace_dir: str, metadata: dict[str, Any] | None = None) -> str | None:
    """Determine best browser launch target (dev server URL or static index.html)."""
    meta = metadata or {}
    dev_url = meta.get("dev_server_url")
    if dev_url:
        return dev_url

    # Check for index.html at root
    root_html = os.path.join(workspace_dir, "index.html")
    if os.path.isfile(root_html):
        return root_html

    # Check first-level subdirectories (e.g. dist, build, templates, public)
    for sub in ("dist", "build", "public", "templates"):
        sub_html = os.path.join(workspace_dir, sub, "index.html")
        if os.path.isfile(sub_html):
            return sub_html

    return None


def launch_job_workspace(job: BuildJob, auto_browser: bool = True) -> dict[str, Any]:
    """Convenience launcher for a BuildJob: opens IDE and optionally browser."""
    vscode_opened = launch_in_vscode(job.workspace_path)

    browser_opened = False
    browser_target = None
    if auto_browser:
        target = find_browser_target(job.workspace_path, job.metadata)
        if target:
            browser_target = target
            browser_opened = open_in_browser(target)

    return {
        "job_id": job.id,
        "workspace_path": job.workspace_path,
        "vscode_opened": vscode_opened,
        "browser_opened": browser_opened,
        "browser_target": browser_target,
    }

"""Desktop and IDE launcher for background build jobs.

Provides safe, subprocess-based launching for VS Code, browser preview,
and desktop notifications without shell=True or blocking calls.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import webbrowser
from typing import Any, Dict, Optional

from core.jobs.models import BuildJob

logger = logging.getLogger("flexie.jobs.launcher")


def find_vscode_executable() -> Optional[str]:
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


def launch_in_vscode(workspace_dir: str) -> bool:
    """Open workspace_dir in VS Code, falling back to os.startfile on Windows."""
    if not os.path.isdir(workspace_dir):
        logger.error("Cannot launch VS Code: workspace directory '%s' does not exist", workspace_dir)
        return False

    code_path = find_vscode_executable()
    if code_path:
        try:
            if code_path.lower().endswith((".cmd", ".bat")):
                cmd = ["cmd.exe", "/c", code_path, workspace_dir]
            else:
                cmd = [code_path, workspace_dir]

            subprocess.Popen(
                cmd,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Launched VS Code for %s using %s", workspace_dir, code_path)
            return True
        except Exception as e:
            logger.warning("Failed to launch VS Code via executable '%s': %s", code_path, e)

    # Fallback to os.startfile / explorer
    try:
        if hasattr(os, "startfile"):
            os.startfile(workspace_dir)
            logger.info("Opened workspace folder via os.startfile: %s", workspace_dir)
            return True
    except Exception as e:
        logger.error("Fallback folder open failed for '%s': %s", workspace_dir, e)

    return False


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


def find_browser_target(workspace_dir: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
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


def launch_job_workspace(job: BuildJob, auto_browser: bool = True) -> Dict[str, Any]:
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

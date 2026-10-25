"""Preflight & Environment Health Checker for Dev Assistant.

Inspects toolchains, models, disk space, and workspace permissions.
Never crashes or raises an exception: failures degrade to structured reports
with clear spoken and logged messages.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger("flexie.preflight")


def _resolve_code_cli() -> Optional[str]:
    """Find VS Code CLI on PATH or standard Windows install locations."""
    which_code = shutil.which("code") or shutil.which("code.cmd")
    if which_code:
        return which_code
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft VS Code\bin\code.cmd"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Code\bin\code.cmd"),
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return None


def _check_binary(name: str, alias_cmd: Optional[str] = None) -> Dict[str, Any]:
    """Check if a CLI binary is installed and executable without raising."""
    try:
        resolved = shutil.which(name) or (shutil.which(alias_cmd) if alias_cmd else None)
        if not resolved:
            return {
                "installed": False,
                "path": None,
                "version": None,
                "message": f"{name} is not installed or not found on PATH.",
                "spoken": f"{name} is not installed.",
            }
        version = None
        try:
            cmd = [resolved, "--version"]
            # Avoid shell=True. On Windows .cmd/.bat need cmd.exe invocation
            if sys.platform == "win32" and resolved.lower().endswith((".cmd", ".bat")):
                cmd = ["cmd.exe", "/c", resolved, "--version"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
                shell=False,
            )
            if res.returncode == 0:
                first_line = res.stdout.strip().splitlines()
                if first_line:
                    version = first_line[0].strip()
        except Exception as ve:
            logger.debug("Failed getting %s version: %s", name, ve)

        ver_str = f" ({version})" if version else ""
        return {
            "installed": True,
            "path": resolved,
            "version": version,
            "message": f"{name} is available at {resolved}{ver_str}.",
            "spoken": f"{name} is ready.",
        }
    except Exception as e:
        logger.warning("Error checking tool %s: %s", name, e)
        return {
            "installed": False,
            "path": None,
            "version": None,
            "message": f"Failed checking {name}: {e}",
            "spoken": f"{name} check failed.",
        }


def run_preflight(workspace_root: Optional[str] = None) -> Dict[str, Any]:
    """Execute preflight health check. Never crashes.

    Returns a structured dict with status of:
    - python version (>= 3.10)
    - git, node, npm, pip, docker, code CLI
    - ollama reachability and pulled models
    - internet connectivity
    - free disk space (>= 2GB)
    - write access to workspace root
    """
    checks: Dict[str, Any] = {}
    missing_tools: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Python version
    try:
        vi = sys.version_info
        py_ver = f"{vi.major}.{vi.minor}.{vi.micro}"
        py_ok = (vi.major, vi.minor) >= (3, 10)
        checks["python"] = {
            "ok": py_ok,
            "version": py_ver,
            "message": f"Python {py_ver} (required >= 3.10)" if py_ok else f"Python {py_ver} is too old (required >= 3.10).",
            "spoken": f"Python {vi.major}.{vi.minor} detected." if py_ok else "Python version is outdated.",
        }
        if not py_ok:
            errors.append(f"Python {py_ver} < 3.10")
    except Exception as e:
        checks["python"] = {
            "ok": False,
            "version": None,
            "message": f"Failed checking Python version: {e}",
            "spoken": "Python check encountered an error.",
        }
        errors.append("Python check error")

    # 2. CLI Toolchains
    for tool_name, alias in [("git", None), ("node", None), ("npm", "npm.cmd"), ("pip", "pip3"), ("docker", None)]:
        tool_res = _check_binary(tool_name, alias)
        checks[tool_name] = {
            "ok": tool_res["installed"],
            "installed": tool_res["installed"],
            "path": tool_res["path"],
            "version": tool_res["version"],
            "message": tool_res["message"],
            "spoken": tool_res["spoken"],
        }
        if not tool_res["installed"]:
            missing_tools.append(tool_name)
            # Docker and node are optional warnings; git and pip are essential
            if tool_name in ("git", "pip"):
                errors.append(f"Missing required tool: {tool_name}")
            else:
                warnings.append(f"Optional tool not found: {tool_name}")

    # 3. VS Code CLI
    try:
        code_path = _resolve_code_cli()
        if code_path:
            checks["code"] = {
                "ok": True,
                "installed": True,
                "path": code_path,
                "message": f"VS Code CLI available at {code_path}.",
                "spoken": "VS Code CLI is ready.",
            }
        else:
            checks["code"] = {
                "ok": False,
                "installed": False,
                "path": None,
                "message": "VS Code CLI ('code') not found on PATH or default locations.",
                "spoken": "VS Code CLI not found.",
            }
            missing_tools.append("code")
            warnings.append("VS Code CLI ('code') not found")
    except Exception as e:
        checks["code"] = {
            "ok": False,
            "installed": False,
            "path": None,
            "message": f"Error probing VS Code CLI: {e}",
            "spoken": "VS Code CLI probe failed.",
        }
        missing_tools.append("code")

    # 4. Ollama reachable & pulled models
    try:
        import urllib.request
        import json
        ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        tags_url = f"{ollama_url}/api/tags"
        req = urllib.request.Request(tags_url, headers={"User-Agent": "FlexiePreflight/2.0"})
        models: List[str] = []
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                for m in payload.get("models", []):
                    name = m.get("name")
                    if name:
                        models.append(name)
        checks["ollama"] = {
            "ok": True,
            "reachable": True,
            "url": ollama_url,
            "models": models,
            "message": f"Ollama reachable at {ollama_url}. Models found: {len(models)}.",
            "spoken": f"Ollama is online with {len(models)} models." if models else "Ollama is online but has no models pulled.",
        }
    except Exception as e:
        checks["ollama"] = {
            "ok": False,
            "reachable": False,
            "url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            "models": [],
            "message": f"Ollama unreachable: {e}",
            "spoken": "Ollama local server is not running.",
        }
        warnings.append("Ollama server unreachable")

    # 5. Internet connectivity
    try:
        from utils.helpers import is_online
        online = is_online()
    except Exception:
        try:
            s = socket.create_connection(("8.8.8.8", 53), timeout=2)
            s.close()
            online = True
        except Exception:
            online = False

    checks["internet"] = {
        "ok": online,
        "online": online,
        "message": "Internet connection active." if online else "Offline / No internet access.",
        "spoken": "Internet is connected." if online else "System is offline.",
    }
    if not online:
        warnings.append("Offline mode active")

    # 6. Disk Space (require >= 2 GB)
    root_to_check = workspace_root or os.getcwd()
    try:
        usage = shutil.disk_usage(root_to_check)
        free_gb = round(usage.free / (1024 ** 3), 2)
        disk_ok = free_gb >= 2.0
        checks["disk_space"] = {
            "ok": disk_ok,
            "free_bytes": usage.free,
            "free_gb": free_gb,
            "required_gb": 2.0,
            "message": f"Free disk space: {free_gb} GB (required >= 2.0 GB).",
            "spoken": f"{free_gb} gigabytes disk space free." if disk_ok else "Low disk space warning: less than 2 gigabytes available.",
        }
        if not disk_ok:
            errors.append(f"Insufficient disk space: {free_gb} GB < 2.0 GB")
    except Exception as e:
        checks["disk_space"] = {
            "ok": False,
            "free_bytes": 0,
            "free_gb": 0.0,
            "required_gb": 2.0,
            "message": f"Could not determine disk usage: {e}",
            "spoken": "Could not check disk space.",
        }
        errors.append("Disk usage check failed")

    # 7. Workspace write access
    target_ws = workspace_root or os.getcwd()
    try:
        os.makedirs(target_ws, exist_ok=True)
        probe_path = os.path.join(target_ws, f".preflight_probe_{os.getpid()}.tmp")
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("probe")
        if os.path.exists(probe_path):
            os.remove(probe_path)
            write_ok = True
        else:
            write_ok = False
        checks["workspace_write"] = {
            "ok": write_ok,
            "path": target_ws,
            "message": f"Workspace root write access verified at {target_ws}.",
            "spoken": "Workspace directory is writable.",
        }
        if not write_ok:
            errors.append(f"Workspace root not writable: {target_ws}")
    except Exception as e:
        checks["workspace_write"] = {
            "ok": False,
            "path": target_ws,
            "message": f"Workspace write check failed at {target_ws}: {e}",
            "spoken": "Workspace root is not writable.",
        }
        errors.append(f"Workspace root write check error: {e}")

    overall_ok = len(errors) == 0

    # Build clear spoken summary
    if overall_ok:
        if missing_tools:
            spoken_summary = f"Preflight passed. Note that {', '.join(missing_tools)} is missing."
        else:
            spoken_summary = "Preflight check passed. All dev tools and workspace are ready."
    else:
        spoken_summary = f"Preflight detected critical issues: {', '.join(errors)}."

    for name, c in checks.items():
        if c.get("ok"):
            logger.info("Preflight [%s]: %s", name, c.get("message"))
        else:
            level = logging.ERROR if name in ("python", "git", "pip", "disk_space", "workspace_write") else logging.WARNING
            logger.log(level, "Preflight [%s]: %s", name, c.get("message"))

    return {
        "overall_ok": overall_ok,
        "checks": checks,
        "missing_tools": missing_tools,
        "warnings": warnings,
        "errors": errors,
        "spoken_summary": spoken_summary,
    }

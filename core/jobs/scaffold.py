"""Scaffolding engine for Build Jobs.

Populates project workspaces with template files, VS Code tasks.json,
PLAN.md, ACCEPTANCE.md, and AGENTS.md.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Optional

from core.jobs.planner import ProjectSpec, write_project_spec_files
from utils.config import Config

logger = logging.getLogger("flexie.jobs.scaffold")

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
)


def scaffold_project(spec: ProjectSpec, workspace_dir: str) -> bool:
    """Scaffold a new project in workspace_dir based on ProjectSpec."""
    try:
        os.makedirs(workspace_dir, exist_ok=True)

        # 1. Write PLAN.md, ACCEPTANCE.md, and AGENTS.md
        write_project_spec_files(spec, workspace_dir)

        # 2. Copy template files if a template was used
        if spec.template_used and spec.template_used != "builtin_fallback":
            tmpl_path = os.path.join(_TEMPLATES_DIR, spec.template_used)
            if os.path.exists(tmpl_path):
                for root, dirs, files in os.walk(tmpl_path):
                    rel_dir = os.path.relpath(root, tmpl_path)
                    target_sub = workspace_dir if rel_dir == "." else os.path.join(workspace_dir, rel_dir)
                    os.makedirs(target_sub, exist_ok=True)

                    for file in files:
                        if file == "manifest.json":
                            continue
                        src_f = os.path.join(root, file)
                        dst_f = os.path.join(target_sub, file)
                        if not os.path.exists(dst_f):
                            shutil.copy2(src_f, dst_f)
                logger.info("Copied template '%s' into %s", spec.template_used, workspace_dir)

        # 3. Create .vscode/tasks.json for convenient run & debug
        vscode_dir = os.path.join(workspace_dir, ".vscode")
        os.makedirs(vscode_dir, exist_ok=True)
        tasks_json = {
            "version": "2.0.0",
            "tasks": [
                {
                    "label": f"Run {spec.title}",
                    "type": "shell",
                    "command": spec.run_command,
                    "group": {"kind": "build", "isDefault": True},
                    "presentation": {"reveal": "always", "panel": "new"},
                }
            ],
        }
        with open(os.path.join(vscode_dir, "tasks.json"), "w", encoding="utf-8") as f:
            json.dump(tasks_json, f, indent=2)

        # 4. Create .vscode/extensions.json for recommended AI & language tools
        recommendations = [
            "saoudrizwan.claude-dev",       # Cline
            "rooveterinaryinc.roo-cline",   # Roo Code
            "esbenp.prettier-vscode",       # Prettier
            "ritwickdey.LiveServer",        # Live Server
        ]
        if spec.stack in ("python", "flask", "python-flask", "python-cli"):
            recommendations.append("ms-python.python")
            recommendations.append("ms-python.vscode-pylance")
        elif spec.stack in ("react", "node", "javascript", "typescript", "react-vite"):
            recommendations.append("dbaeumer.vscode-eslint")
            recommendations.append("bradlc.vscode-tailwindcss")

        extensions_json = {"recommendations": recommendations}
        with open(os.path.join(vscode_dir, "extensions.json"), "w", encoding="utf-8") as f:
            json.dump(extensions_json, f, indent=2)

        # 5. Create .vscode/settings.json pre-wired to local AI bridge / Ollama
        _bridge_port = getattr(Config, "OPENAI_BRIDGE_PORT", 9899)
        _bridge_key  = getattr(Config, "JOB_BRIDGE_API_KEY", "flexie-local-bridge")
        _bridge_url  = f"http://127.0.0.1:{_bridge_port}/v1"
        settings_json = {
            "editor.formatOnSave": True,
            "cline.apiProvider": "openai-compatible",
            "cline.baseUrl": _bridge_url,
            "cline.apiKey": _bridge_key,
            "roo-cline.apiProvider": "openai-compatible",
            "roo-cline.baseUrl": _bridge_url,
            "roo-cline.apiKey": _bridge_key,
            "files.exclude": {
                "**/__pycache__": True,
                "**/.git": True,
                "**/.pytest_cache": True,
                "**/node_modules": True,
                "**/.venv": True,
            },
        }
        with open(os.path.join(vscode_dir, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings_json, f, indent=2)

        # 6. Create .clinerules for AI assistant workspace context
        clinerules_content = (
            f"# {spec.title} - AI Assistant Workspace Directives\n\n"
            "This project was autonomously scaffolded by Flexie Dev Assistant.\n\n"
            "## Architecture & Workflow Rules\n"
            "1. Read `PLAN.md` before making architectural or structural changes.\n"
            "2. Read and verify requirements against `ACCEPTANCE.md` before concluding any feature.\n"
            "3. Follow the development guidelines in `AGENTS.md`.\n"
            "4. Always test and verify code stability before saving edits.\n"
        )
        with open(os.path.join(workspace_dir, ".clinerules"), "w", encoding="utf-8") as f:
            f.write(clinerules_content)

        return True
    except Exception as e:
        logger.error("Scaffolding failed for %s: %s", workspace_dir, e)
        return False

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

        return True
    except Exception as e:
        logger.error("Scaffolding failed for %s: %s", workspace_dir, e)
        return False

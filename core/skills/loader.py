"""Skill loading and catalog generation.

A skill is a directory containing SKILL.md (instruction-only) and optionally
skill.toml (structured pipeline). This module implements the instruction-only
format first; pipelines can be added without changing the catalog contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    instructions: str
    tags: list[str] = field(default_factory=list)


def default_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    header = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    meta: dict = {}
    for line in header.splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key == "tags" and value.startswith("[") and value.endswith("]"):
            meta[key] = [t.strip().strip("\"'") for t in value[1:-1].split(",") if t.strip()]
        else:
            meta[key] = value
    return meta, body


def load_skill(path: Path) -> Skill | None:
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    meta, body = _split_frontmatter(text)
    name = meta.get("name") or path.name
    description = meta.get("description", "")
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return Skill(name=name, description=description, path=path, instructions=body.strip(), tags=tags)


def discover_skills(root: Path | None = None) -> list[Skill]:
    root = root or default_skills_root()
    if not root.is_dir():
        return []
    skills = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            skill = load_skill(child)
            if skill:
                skills.append(skill)
    return skills


def find_skill(name: str, root: Path | None = None) -> Skill | None:
    for skill in discover_skills(root):
        if skill.name == name:
            return skill
    return None


def _escape(value: str) -> str:
    return re.sub(r"[<>&]", "", value).strip()

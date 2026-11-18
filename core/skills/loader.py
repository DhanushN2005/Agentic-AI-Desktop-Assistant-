"""Skill loading and catalog generation.

A skill is a directory containing SKILL.md (instruction-only) and optionally
skill.toml (structured pipeline). This module implements the instruction-only
format first; pipelines can be added without changing the catalog contract.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_DESCRIPTION = 200
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_logger = logging.getLogger("Flexie.Skills")
# root -> (signature, skills): discovery re-parses only when a SKILL.md changed
_DISCOVER_CACHE: dict[str, tuple[tuple, list]] = {}


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
    if not _NAME_RE.match(name) or name != path.name:
        _logger.warning("Skipping skill in %s: name %r must match [a-z0-9-]+ and the directory name",
                        path.name, name)
        return None
    description = _CTRL_RE.sub(" ", meta.get("description", "")).strip()[:MAX_DESCRIPTION]
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return Skill(name=name, description=description, path=path, instructions=body.strip(), tags=tags)


def _signature(root: Path) -> tuple:
    sig = []
    with os.scandir(root) as it:
        for entry in it:
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            try:
                st = os.stat(os.path.join(entry.path, "SKILL.md"))
                sig.append((entry.name, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((entry.name, 0, 0))
    return tuple(sorted(sig))


def discover_skills(root: Path | None = None) -> list[Skill]:
    root = root or default_skills_root()
    if not root.is_dir():
        return []
    key = str(root)
    try:
        sig = _signature(root)
    except OSError:
        sig = None
    cached = _DISCOVER_CACHE.get(key)
    if sig is not None and cached is not None and cached[0] == sig:
        return list(cached[1])
    skills = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            skill = load_skill(child)
            if skill:
                skills.append(skill)
    if sig is not None:
        _DISCOVER_CACHE[key] = (sig, list(skills))
    return skills


def find_skill(name: str, root: Path | None = None) -> Skill | None:
    for skill in discover_skills(root):
        if skill.name == name:
            return skill
    return None


def _escape(value: str) -> str:
    """Make ``value`` safe inside a double-quoted XML-ish attribute (no control chars)."""
    value = _CTRL_RE.sub(" ", value).strip()
    return (value.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

"""Render the available-skills catalog for a system prompt."""
from __future__ import annotations

from core.skills.loader import Skill, _escape


def build_catalog(skills: list[Skill]) -> str:
    if not skills:
        return ""
    lines = ["<available_skills>"]
    for skill in skills:
        lines.append(f'  <skill name="{_escape(skill.name)}" description="{_escape(skill.description)}" />')
    lines.append("</available_skills>")
    return "\n".join(lines)

from core.skills import build_catalog, discover_skills, find_skill


def _write_skill(root, name, description):
    directory = root / name
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ntags: [test, demo]\n---\n\nDo the thing.\n",
        encoding="utf-8",
    )


def test_discover_and_catalog(tmp_path):
    _write_skill(tmp_path, "demo-skill", "A demo skill")
    skills = discover_skills(tmp_path)
    assert [skill.name for skill in skills] == ["demo-skill"]
    catalog = build_catalog(skills)
    assert "<available_skills>" in catalog
    assert 'name="demo-skill"' in catalog
    assert "A demo skill" in catalog


def test_find_skill_returns_instructions(tmp_path):
    _write_skill(tmp_path, "demo-skill", "A demo skill")
    skill = find_skill("demo-skill", tmp_path)
    assert skill is not None
    assert "Do the thing." in skill.instructions
    assert skill.tags == ["test", "demo"]

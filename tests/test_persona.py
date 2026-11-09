from core.persona import compose_system_prompt, load_persona


def test_load_persona_from_directory(tmp_path, monkeypatch):
    (tmp_path / "SOUL.md").write_text("Be concise.", encoding="utf-8")
    (tmp_path / "USER.md").write_text("Developer.", encoding="utf-8")
    monkeypatch.setenv("FLEXIE_PERSONA_DIR", str(tmp_path))
    text = load_persona()
    assert "## SOUL" in text and "Be concise." in text
    assert "## USER" in text and "Developer." in text


def test_persona_none_disables_injection(tmp_path, monkeypatch):
    (tmp_path / "SOUL.md").write_text("Be concise.", encoding="utf-8")
    monkeypatch.setenv("FLEXIE_PERSONA_DIR", str(tmp_path))
    assert load_persona("none") == ""
    assert compose_system_prompt("BASE", "none") == "BASE"


def test_compose_appends_persona(tmp_path, monkeypatch):
    (tmp_path / "SOUL.md").write_text("Be concise.", encoding="utf-8")
    monkeypatch.setenv("FLEXIE_PERSONA_DIR", str(tmp_path))
    prompt = compose_system_prompt("BASE")
    assert prompt.startswith("BASE")
    assert "PERSISTENT PERSONA" in prompt

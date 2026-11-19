"""Dashboard settings: validation, live apply (no restart) and the orb style choice."""
import json

import pytest

from core import settings_service as ss
from utils.config import Config


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point the .env writer at a temp file so tests never touch the real one, and restore Config afterwards."""
    import utils.config as cfg
    monkeypatch.setattr(cfg, "_env_path", lambda: str(tmp_path / ".env"))
    saved = {b["attr"]: getattr(Config, b["attr"]) for b in ss.BEHAVIOR if b["attr"]}
    saved_env = {b["env"]: cfg.os.environ.get(b["env"]) for b in ss.BEHAVIOR} | {"FLEXIE_ORB_STYLE": cfg.os.environ.get("FLEXIE_ORB_STYLE")}
    yield tmp_path / ".env"
    for attr, value in saved.items():
        setattr(Config, attr, value)
    for k, v in saved_env.items():
        if v is None:
            cfg.os.environ.pop(k, None)
        else:
            cfg.os.environ[k] = v


def test_snapshot_lists_behaviour_orb_styles_and_modes_without_secrets():
    snap = ss.snapshot()
    assert {b["env"] for b in snap["behavior"]} == {b["env"] for b in ss.BEHAVIOR}
    assert all("value" in b and "attr" not in b for b in snap["behavior"])
    assert snap["orb"]["choices"] == list(ss.ORB_STYLES) and snap["orb"]["style"] in ss.ORB_STYLES
    assert snap["modes"] == list(Config.MODES)
    dumped = json.dumps(snap)
    import os
    for meta in ss.SUPPORTED_PROVIDERS.values():          # no real key may ever appear in what the dashboard can see
        secret = os.environ.get(meta["env"], "")
        assert len(secret) < 8 or secret not in dumped


def test_behaviour_settings_apply_live_without_a_restart(env_file):
    changed, problems = ss.apply({"behavior": {"FLEXIE_CONVERSATION_HISTORY_TURNS": 3, "FLEXIE_LLM_REQUEST_TIMEOUT": "11.5",
                                               "FLEXIE_CHEAP_FIRST_ENABLED": False}})
    assert (changed, problems) == (3, [])
    assert Config.CONVERSATION_HISTORY_TURNS == 3 and Config.LLM_REQUEST_TIMEOUT == 11.5 and Config.CHEAP_FIRST_ENABLED is False
    text = env_file.read_text(encoding="utf-8")
    assert "FLEXIE_CONVERSATION_HISTORY_TURNS=3" in text and "FLEXIE_CHEAP_FIRST_ENABLED=0" in text
    assert ss.apply({"behavior": {"FLEXIE_CONVERSATION_HISTORY_TURNS": 3}}) == (0, [])      # unchanged value: nothing written


@pytest.mark.parametrize("bad", [
    {"FLEXIE_CONVERSATION_HISTORY_TURNS": 999}, {"FLEXIE_CONVERSATION_HISTORY_TURNS": "abc"}, {"FLEXIE_LLM_REQUEST_TIMEOUT": -1},
    {"FLEXIE_TTS_MODE": "robot"}, {"FLEXIE_NOT_A_SETTING": 1}, {"PATH": "evil"}, {"FLEXIE_CODE_MAX_TOKENS": True},
])
def test_invalid_behaviour_values_are_rejected_and_nothing_is_written(env_file, bad):
    before = Config.CONVERSATION_HISTORY_TURNS
    changed, problems = ss.apply({"behavior": bad})
    assert changed == 0 and problems and Config.CONVERSATION_HISTORY_TURNS == before and not env_file.exists()


def test_restart_only_setting_is_saved_but_not_pushed_onto_config(env_file):
    target = "sapi" if ss._current(ss._BEHAVIOR_BY_ENV["FLEXIE_TTS_MODE"]) != "sapi" else "neural"
    assert ss.apply({"behavior": {"FLEXIE_TTS_MODE": target}}) == (1, [])
    assert f"FLEXIE_TTS_MODE={target}" in env_file.read_text(encoding="utf-8")
    assert next(b for b in ss.BEHAVIOR if b["env"] == "FLEXIE_TTS_MODE")["live"] is False


def test_orb_style_is_validated_saved_and_reported(env_file):
    assert ss.apply({"orb_style": "eye"}) == (1, []) and ss.orb_style() == "eye"
    changed, problems = ss.apply({"orb_style": "../../etc"})
    assert changed == 0 and problems and ss.orb_style() == "eye"
    assert ss.apply({"orb_style": "eye"}) == (0, [])


def test_orchestrator_tells_the_floating_orb_to_switch_after_saving():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assert 'send_to_ui("ORB_STYLE", orb_style())' in src and "self.brain.reload_providers()" in src
    assert 'metrics["disk"]' in src and 'metrics["net"]' in src

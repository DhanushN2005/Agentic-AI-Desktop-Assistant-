"""Volume up / down / set / mute against a fake Windows audio endpoint (so tests never touch real speakers)."""
import types

import pytest

from core.handlers import system as sysh
from engines.system import SystemCtrl


class FakeEndpoint:
    def __init__(self, volume=40, muted=False):
        self.v, self.m = volume / 100.0, muted

    def GetMasterVolumeLevelScalar(self):
        return self.v

    def SetMasterVolumeLevelScalar(self, scalar, ctx):
        self.v = scalar

    def GetMute(self):
        return self.m

    def SetMute(self, flag, ctx):
        self.m = bool(flag)


@pytest.fixture
def audio(monkeypatch):
    ep = FakeEndpoint()
    monkeypatch.setattr(SystemCtrl, "_endpoint", staticmethod(lambda: ep))
    said = []
    orch = types.SimpleNamespace(speak=lambda t, **k: said.append(t))
    return ep, orch, said


def vol(ep):
    return round(ep.v * 100)


@pytest.mark.parametrize("phrase,expected", [
    ("increase volume", 50), ("volume up", 50), ("turn up the volume", 50), ("louder", 50), ("raise the volume", 50),
    ("decrease volume", 30), ("volume down", 30), ("turn the volume down", 30), ("quieter", 30), ("lower the volume", 30),
    ("increase the volume a little", 45), ("turn it up a lot", 65), ("volume down a bit", 35),
    ("set volume to 70", 70), ("volume 25", 25), ("increase volume by 15", 55), ("decrease volume by 15", 25), ("volume to 150", 100),
    ("max volume", 100), ("minimum volume", 0),
])
def test_volume_phrases_change_the_real_value_and_say_what_it_is_now(audio, phrase, expected):
    ep, orch, said = audio
    assert sysh.handle_volume(orch, phrase, False) is True
    assert vol(ep) == expected, phrase
    assert said[-1] == f"Volume is {expected} percent.", said


def test_mute_and_unmute_use_the_real_mute_switch_and_keep_the_level(audio):
    ep, orch, said = audio
    sysh.handle_volume(orch, "mute", False)
    assert ep.m is True and vol(ep) == 40 and said[-1] == "Muted."
    sysh.handle_volume(orch, "unmute", False)
    assert ep.m is False and vol(ep) == 40 and "Unmuted" in said[-1]
    sysh.handle_volume(orch, "mute", False)
    sysh.handle_volume(orch, "increase volume", False)               # turning it up while muted must be audible
    assert ep.m is False and vol(ep) == 50


def test_unmute_from_zero_picks_a_audible_level(audio):
    ep, orch, said = audio
    ep.v = 0.0
    sysh.handle_volume(orch, "unmute", False)
    assert vol(ep) == 30


def test_when_windows_audio_is_unreachable_flexie_says_so_instead_of_pretending(monkeypatch):
    def boom():
        raise AttributeError("'AudioDevice' object has no attribute 'Activate'")
    monkeypatch.setattr(SystemCtrl, "_endpoint", staticmethod(boom))
    said = []
    orch = types.SimpleNamespace(speak=lambda t, **k: said.append(t))
    assert SystemCtrl.get_volume() is None and SystemCtrl.set_volume(50) is False
    sysh.handle_volume(orch, "increase volume", False)
    assert "can't reach" in said[-1].lower() and "percent" not in said[-1]


def test_new_and_old_pycaw_shapes_are_both_supported(monkeypatch):
    new_style = types.SimpleNamespace(EndpointVolume="NEW")
    monkeypatch.setattr("engines.system.AudioUtilities", types.SimpleNamespace(GetSpeakers=lambda: new_style))
    assert SystemCtrl._endpoint() == "NEW"
    old_style = types.SimpleNamespace(Activate=lambda iid, ctx, p: (_ for _ in ()).throw(RuntimeError("old path used")))
    monkeypatch.setattr("engines.system.AudioUtilities", types.SimpleNamespace(GetSpeakers=lambda: old_style))
    with pytest.raises(RuntimeError, match="old path used"):
        SystemCtrl._endpoint()


def test_date_pause_and_connection_questions_are_answered_locally():
    import re
    import types as _t

    from core.handlers.alarm import handle_alarm
    from core.handlers.tools import handle_status
    from core.router import IntentRouter
    R = IntentRouter()
    for phrase, intent in (("what's the date", "alarm"), ("what day is it", "alarm"), ("pause", "media"), ("wifi status", "status"),
                           ("am i online", "status"), ("battery status", "status"), ("what is the date of the next holiday", "search")):
        assert R.route(phrase)[0] == intent, phrase
    said = []
    ctx = _t.SimpleNamespace(pending_action=None, update=lambda **k: None, clear_pending_action=lambda: None)
    orch = _t.SimpleNamespace(speak=lambda t, **k: said.append(t), send_to_ui=lambda *a: None, ctx=ctx)
    assert handle_alarm(orch, "what's the date") is True
    assert re.fullmatch(r"Today is \w+, \d{1,2} \w+ \d{4}\.", said[-1]), said[-1]
    orch2 = _t.SimpleNamespace(speak=lambda t, **k: said.append(t))
    handle_status(orch2, "wifi status")
    assert "connected" in said[-1].lower() or "wi-fi" in said[-1].lower()
    handle_status(orch2, "battery status")
    assert said[-1].startswith("Battery is at") and "CPU" not in said[-1]

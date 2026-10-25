"""Regression tests for the persistent-mic VAD in interface/voice.py.

These pin the fix for "I talk but Flexie never listens":

  * frame level and ambient floor must be compared in the SAME units
    (raw 16-bit RMS, i.e. audioop.rms / recognizer.energy_threshold scale),
  * normal speech (raw RMS ~1000) must trigger,
  * room ambience (~raw RMS 20) must not,
  * webrtcvad must be fed valid 30 ms frames.

No hardware, no network and no TTS engine is used: the mic stream and the
recognizer are faked.
"""

import math
import struct
import threading

import interface.voice as voice_module
from interface.voice import VAD_FRAME_MS, VoiceInterface


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class FakeStream:
    """Emits queued frames; after the queue drains it emits the tail forever."""

    def __init__(self, frames, tail=b""):
        self._frames = list(frames)
        self._tail = tail
        self.reads = 0

    def read(self, chunk_size):
        self.reads += 1
        if self._frames:
            return self._frames.pop(0)
        return self._tail


class FakeMic:
    """Minimal stand-in for speech_recognition.Microphone."""

    SAMPLE_RATE = 16000
    SAMPLE_WIDTH = 2

    def __init__(self, stream):
        self.stream = stream


class FakeRecognizer:
    energy_threshold = 300.0
    pause_threshold = 0.8
    non_speaking_duration = 0.4

    def __init__(self):
        self.google_calls = 0

    def recognize_google(self, audio_data, language=None):
        self.google_calls += 1
        raise AssertionError("network ASR must not be reached in this test")


def make_voice(frames, tail):
    """Build a VoiceInterface without touching PyAudio, TTS or the network."""
    v = object.__new__(VoiceInterface)
    v.recognizer = FakeRecognizer()
    v._mic = FakeMic(FakeStream(frames, tail))
    v._mic_context = v._mic  # truthy -> skips __enter__
    v._mic_sample_rate = FakeMic.SAMPLE_RATE
    v.lang = "en-IN"
    v._asr_lock = threading.Lock()
    v.is_speaking = False
    v._speech_buffer = ""
    v.sent_ui = []
    v.send_to_ui = lambda tag, value: v.sent_ui.append((tag, value))
    v._recognize_offline = lambda audio_data, raw, rate: "open notepad"
    return v


def frame(amplitude, sample_rate=16000, ms=VAD_FRAME_MS):
    """One 30 ms int16 frame of a sine wave at the given peak amplitude."""
    n = int(sample_rate * ms / 1000)
    data = struct.pack(
        f"{n}h", *(int(amplitude * math.sin(2 * math.pi * 220 * i / sample_rate)) for i in range(n))
    )
    return data


def silence_frame(sample_rate=16000, ms=VAD_FRAME_MS):
    """Quiet room: tiny +/-20 LSB dither (raw RMS ~12)."""
    n = int(sample_rate * ms / 1000)
    return struct.pack(f"{n}h", *((-20 if i % 2 else 20) for i in range(n)))


def raw_rms(data):
    count = len(data) // 2
    return math.sqrt(sum(float(s) ** 2 for s in struct.unpack(f"{count}h", data)) / count)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_frame_level_matches_raw_rms_scale():
    """The VAD must see raw int16 RMS, not a /32768*1000 rescaled value."""
    f = frame(1500)
    assert 900 < raw_rms(f) < 1200  # amplitude 1500 -> RMS ~1060

    # The old code scaled by (s/32768)**2*1000, which yielded ~32 for this
    # frame and so never beat its own 80.0 floor.
    old_rms = math.sqrt(sum((s / 32768.0) ** 2 for s in struct.unpack(f"{len(f) // 2}h", f)) / (len(f) // 2)) * 1000
    assert old_rms < 80.0 < raw_rms(f)


def test_webrtcvad_uses_30ms_frames():
    """webrtcvad rejects 60 ms frames (the old chunk size) at 16 kHz."""
    import webrtcvad

    vad = webrtcvad.Vad(2)
    assert VAD_FRAME_MS == 30
    assert len(frame(1000)) == int(16000 * 30 / 1000) * 2
    vad.is_speech(frame(1000), 16000)  # must not raise

    try:
        vad.is_speech(b"\x00\x00" * 960, 16000)  # 60 ms frame
    except Exception as e:
        assert "frame" in str(e).lower()
    else:
        raise AssertionError("webrtcvad accepted an invalid 60 ms frame")


def test_speech_is_detected_and_transcribed(monkeypatch):
    monkeypatch.setattr(voice_module, "is_online", lambda: False)
    frames = [silence_frame() for _ in range(10)]          # 0.3s room tone
    frames += [frame(1500) for _ in range(40)]             # 1.2s of talking
    v = make_voice(frames, tail=silence_frame())           # then silence

    result = v.listen_adaptive(mode="normal")

    assert result == "open notepad"
    assert any(tag == "STATE" and value == "LISTENING" for tag, value in v.sent_ui)


def test_ambient_silence_never_triggers(monkeypatch):
    monkeypatch.setattr(voice_module, "is_online", lambda: False)
    v = make_voice([], tail=silence_frame())

    # Short wait window keeps the test fast; nothing should ever be captured.
    assert v.listen_adaptive(mode="fast", timeout=0.3) == ""


def test_single_frame_blip_is_rejected(monkeypatch):
    """One isolated loud frame (click/keyboard) must not open an utterance."""
    monkeypatch.setattr(voice_module, "is_online", lambda: False)
    frames = [silence_frame() for _ in range(5)]
    frames += [frame(1500)]                                # single blip
    frames += [silence_frame() for _ in range(40)]
    v = make_voice(frames, tail=silence_frame())

    assert v.listen_adaptive(mode="fast", timeout=0.3) == ""


def test_deaf_old_threshold_would_miss_normal_speech():
    """Guard the exact bug: amplitude 1500 speech never beat the old 80.0 floor."""
    f = frame(1500)
    old_floor = 80.0
    count = len(f) // 2
    old_rms = math.sqrt(sum((s / 32768.0) ** 2 for s in struct.unpack(f"{count}h", f)) / count) * 1000
    assert old_rms < old_floor, "old code could not hear this (that was the bug)"
    assert raw_rms(f) > 150.0, "new floor (raw RMS 150) must be crossed"

"""Flexie voice-input diagnostic.

Reproduces the exact VAD math used by interface/voice.py and prints it, so you
can see whether your microphone actually hears you.

Run:  python tools/voice_diag.py [seconds]
"""

import math
import os
import struct
import sys
import time

# Allow running straight from the repo root: python tools/voice_diag.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import speech_recognition as sr  # noqa: E402

from interface.voice import VAD_ENERGY_RATIO, VAD_FRAME_MS, VAD_MIN_ENERGY  # noqa: E402


def raw_rms(raw: bytes) -> float:
    """Raw int16 RMS — same scale as recognizer.energy_threshold (audioop.rms)."""
    count = len(raw) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", raw)
    return math.sqrt(sum(float(s) * float(s) for s in shorts) / count)


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

    print("== Input devices ==")
    names = sr.Microphone.list_microphone_names()
    for i, name in enumerate(names):
        print(f"  [{i}] {name}")
    print("  Tip: set FLEXIE_MIC_DEVICE=<index or name substring> in .env to pin one.")

    # Mirrors VoiceInterface._open_mic_stream(): 16 kHz first, device default as fallback.
    try:
        mic = sr.Microphone(sample_rate=16000)
    except Exception as e:
        print(f"\n16 kHz open failed ({e}); falling back to device default rate")
        mic = sr.Microphone()

    rec = sr.Recognizer()
    with mic as source:
        sample_rate = source.SAMPLE_RATE
        print(f"\n== Mic @ {sample_rate} Hz ==")
        print("== Calibrating (adjust_for_ambient_noise, 1.5s) ==")
        rec.adjust_for_ambient_noise(source, duration=1.5)
        print(f"recognizer.energy_threshold = {rec.energy_threshold:.1f} (raw RMS)")

        chunk = max(1, int(sample_rate * (VAD_FRAME_MS / 1000.0)))
        noise_floor = max(float(rec.energy_threshold), VAD_MIN_ENERGY)

        print(f"\n== Recording {seconds:.0f}s — SPEAK NOW ==")
        print(f"{'t':>5} {'rms':>8} {'peak':>7} {'thr':>7} {'speech?':>8}")

        start = time.time()
        while time.time() - start < seconds:
            raw = source.stream.read(chunk)
            shorts = struct.unpack(f"{len(raw) // 2}h", raw)
            r = raw_rms(raw)
            peak = max(max(shorts), -min(shorts))

            try:
                import webrtcvad
                webrtc = webrtcvad.Vad(2).is_speech(raw, sample_rate) if sample_rate in (8000, 16000, 32000, 48000) else None
            except Exception:
                webrtc = None

            thr = max(noise_floor * VAD_ENERGY_RATIO, VAD_MIN_ENERGY)
            speech_frame = r > thr or bool(webrtc)
            if not speech_frame:
                # Same "adapt only while silent" rule as listen_adaptive().
                noise_floor = max(noise_floor * 0.95 + r * 0.05, VAD_MIN_ENERGY * 0.25)

            print(f"{time.time() - start:5.1f} {r:8.1f} {peak:7d} {thr:7.1f} "
                  f"{('YES' if speech_frame else 'no'):>8}{'  (webrtcvad)' if webrtc else ''}")

        print("\n-- How to read this --")
        print(f"Any spoken frame whose rms beats 'thr' triggers the assistant (floor {VAD_MIN_ENERGY:.0f}).")
        print("If rms never rises while you talk, the mic itself (device/privacy/mute) is the problem.")
        print("If it rises but stays below 'thr', lower FLEXIE_VAD_MIN_ENERGY in .env.")


if __name__ == "__main__":
    main()

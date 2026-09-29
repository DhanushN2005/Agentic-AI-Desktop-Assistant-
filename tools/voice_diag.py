"""Flexie voice-input diagnostic.

Reproduces the exact VAD math used by interface/voice.py (lines ~456-492) and
prints it side by side with SpeechRecognition's own energy scale so the unit
mismatch (if any) is obvious.

Run:  python tools/voice_diag.py [seconds]
"""

import math
import struct
import sys
import time

import speech_recognition as sr


def scaled_rms(raw: bytes) -> float:
    """Exactly what VoiceInterface.listen_adaptive() computes."""
    count = len(raw) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", raw)
    sum_squares = sum((s / 32768.0) ** 2 for s in shorts)
    return math.sqrt(sum_squares / count) * 1000


def raw_rms(raw: bytes) -> float:
    """What SpeechRecognition's recognizer.energy_threshold uses (audioop.rms)."""
    count = len(raw) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", raw)
    sum_squares = sum(float(s) * float(s) for s in shorts)
    return math.sqrt(sum_squares / count)


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

    print("== Input devices ==")
    for i, name in enumerate(sr.Microphone.list_microphone_names()):
        marker = "  <-- DEFAULT (used by sr.Microphone())" if i == 1 else ""
        print(f"  [{i}] {name}{marker}")

    rec = sr.Recognizer()
    mic = sr.Microphone()
    with mic as source:
        print("\n== Calibrating (adjust_for_ambient_noise, 1.5s) ==")
        rec.adjust_for_ambient_noise(source, duration=1.5)
        print(f"recognizer.energy_threshold = {rec.energy_threshold:.1f}  "
              f"(RAW units -> equals {rec.energy_threshold / 32.768:.2f} in VAD units)")

        sample_rate = source.SAMPLE_RATE
        chunk = int(sample_rate * 0.06)
        noise_floor = rec.energy_threshold
        print(f"\n== Recording {seconds:.0f}s — SPEAK NOW ==")
        print(f"{'t':>5} {'VAD rms':>9} {'raw rms':>9} {'peak':>7} "
              f"{'vad_thr':>8} {'speech?':>8}")

        start = time.time()
        while time.time() - start < seconds:
            raw = source.stream.read(chunk)
            r = scaled_rms(raw)
            rr = raw_rms(raw)
            peak = max(abs(s) for s in struct.unpack(f"{len(raw) // 2}h", raw))
            noise_floor = max((noise_floor * 0.95) + (r * 0.05), 35.0)
            thr = max(noise_floor * 1.5, 80.0)

            try:
                import webrtcvad
                webrtc = webrtcvad.Vad(2).is_speech(raw, sample_rate)
            except Exception:
                webrtc = None

            detected = (r > thr) or bool(webrtc)
            print(f"{time.time() - start:5.1f} {r:9.1f} {rr:9.1f} {peak:7d} "
                  f"{thr:8.1f} {('YES' if detected else 'no'):>8}"
                  f"{'   (webrtcvad=True)' if webrtc else ''}")

        print("\n-- Notes --")
        print("Whatever the VAD rms column shows while you are talking must beat the")
        print("vad_thr column. The 80.0 floor is what list_adaptive falls back to.")


if __name__ == "__main__":
    main()

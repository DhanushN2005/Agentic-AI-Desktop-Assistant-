import webrtcvad

v = webrtcvad.Vad(2)
for ms, rate in ((60, 16000), (30, 16000), (20, 16000), (10, 16000)):
    n = int(rate * ms / 1000)
    buf = b"\x00\x00" * n
    try:
        print(f"  {ms}ms frame ({n} samples) -> OK, speech={v.is_speech(buf, rate)}")
    except Exception as e:
        print(f"  {ms}ms frame ({n} samples) -> ERROR: {type(e).__name__}: {e}")

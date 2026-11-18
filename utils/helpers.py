import logging
import os
import re
import shutil
import socket
import threading
import time


def find_executable(name: str, default_path: str = None) -> str:
    # Try shutil.which first
    path = shutil.which(name)
    if path:
        return path

    # If not found and default_path exists, check it
    if default_path and os.path.exists(default_path):
        return default_path

    return default_path or name

# Short TTL cache — avoids a live probe on every TTS/ASR call while still
# noticing a dropped connection within ~10 s.
_ONLINE_TTL = 10.0
_PROBE_TIMEOUT = 2.0
_PROBE_TARGETS = (("8.8.8.8", 53), ("1.1.1.1", 443), ("dns.google", 443))
_online_cache: dict = {"val": True, "ts": 0.0}
_online_lock = threading.Lock()


def _probe(target, ok: threading.Event) -> None:
    try:
        # Per-socket timeout: never touch the process-wide socket default.
        with socket.create_connection(target, timeout=_PROBE_TIMEOUT):
            ok.set()
    except Exception as _e:
        logging.debug("[utils/helpers.py] is_online probe %s failed: %s: %s", target[0], type(_e).__name__, _e)


def is_online() -> bool:
    now = time.monotonic()
    if now - _online_cache["ts"] < _ONLINE_TTL:
        return _online_cache["val"]
    with _online_lock:
        now = time.monotonic()
        if now - _online_cache["ts"] < _ONLINE_TTL:  # another thread just probed
            return _online_cache["val"]
        ok = threading.Event()
        threads = [threading.Thread(target=_probe, args=(t, ok), daemon=True) for t in _PROBE_TARGETS]
        for t in threads:
            t.start()
        deadline = time.monotonic() + _PROBE_TIMEOUT + 0.5
        # Return as soon as any host answers; otherwise wait for all (bounded).
        while not ok.is_set() and any(t.is_alive() for t in threads) and time.monotonic() < deadline:
            ok.wait(0.05)
        _online_cache["val"] = ok.is_set()
        _online_cache["ts"] = time.monotonic()
        return _online_cache["val"]

def get_numbers(text: str) -> list[int]:
    return [int(x) for x in re.findall(r'\d+', text)]

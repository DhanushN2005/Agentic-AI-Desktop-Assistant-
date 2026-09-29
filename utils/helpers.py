import os
import re
import shutil
import socket
import time
import logging


def find_executable(name: str, default_path: str = None) -> str:
    # Try shutil.which first
    path = shutil.which(name)
    if path:
        return path

    # If not found and default_path exists, check it
    if default_path and os.path.exists(default_path):
        return default_path

    return default_path or name

# 30-second TTL cache — avoids a live DNS probe on every TTS/ASR call.
_online_cache: dict = {"val": True, "ts": 0.0}

def is_online() -> bool:
    now = time.monotonic()
    if now - _online_cache["ts"] < 30.0:
        return _online_cache["val"]
    try:
        socket.setdefaulttimeout(2)
        s = socket.create_connection(("8.8.8.8", 53))
        s.close()
        _online_cache["val"] = True
    except Exception as _e:
        logging.debug("[utils/helpers.py] is_online probe failed: %s: %s", type(_e).__name__, _e)
        _online_cache["val"] = False
    _online_cache["ts"] = now
    return _online_cache["val"]

def get_numbers(text: str) -> list[int]:
    return [int(x) for x in re.findall(r'\d+', text)]

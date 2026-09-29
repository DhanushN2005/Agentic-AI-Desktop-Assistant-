import os
import re
import shutil
import socket
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

def is_online() -> bool:
    try:
        socket.setdefaulttimeout(2)
        s = socket.create_connection(("8.8.8.8", 53))
        s.close()
        return True
    except Exception as _e:
        logging.debug("[utils/helpers.py:25] Swallowed exception: %s: %s", type(_e).__name__, _e)
        return False

def get_numbers(text: str) -> list[int]:
    return [int(x) for x in re.findall(r'\d+', text)]

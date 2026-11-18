"""Project-anchored paths for runtime data (databases, logs).

Bare relative names like ``flexie_memory.db`` resolve against the process working
directory, so starting Flexie from another folder silently created a second,
empty memory. ``data_file`` anchors them to the project root (or the directory in
``FLEXIE_DATA_DIR``), independent of the working directory.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    return os.path.abspath(os.getenv("FLEXIE_DATA_DIR") or PROJECT_ROOT)


def data_file(name: str) -> str:
    """Absolute path for a runtime data file; absolute inputs pass through unchanged."""
    if os.path.isabs(name):
        return name
    return os.path.join(data_dir(), name)

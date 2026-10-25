"""Workspace path jail — fail-closed path validation for file tools.

``resolve_in_root(path, root)`` resolves ``path`` (relative → joined to
``root``) through symlinks via ``os.path.realpath`` and requires the result
to stay inside ``root`` (checked with ``os.path.commonpath``). Anything else
— ``..`` escapes, absolute paths outside the root, symlink escapes —
raises ``ValueError``.
"""
import os

_SYSTEM_DIR_NAMES = {"windows", "program files", "program files (x86)", "programdata"}
_WIN_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_in_root(path: str, root: str) -> str:
    if not path or not path.strip():
        raise ValueError("empty path")
    p = path.strip()
    # Strip surrounding quotes users sometimes include
    if len(p) >= 2 and p[0] == p[-1] and p[0] in ("'", '"'):
        p = p[1:-1]
    for part in os.path.normpath(p).split(os.sep):
        if part:
            stem = part.split(".")[0].lower()
            if stem in _WIN_RESERVED_NAMES:
                raise ValueError(f"reserved Windows device name in path: {part!r}")
    joined = p if os.path.isabs(p) else os.path.join(root, p)
    real = os.path.realpath(os.path.abspath(joined))
    real_root = os.path.realpath(os.path.abspath(root))
    try:
        inside = os.path.commonpath([real, real_root]) == real_root
    except ValueError:
        inside = False  # e.g. different drives on Windows
    if not inside:
        raise ValueError(f"path escapes workspace root: {path!r}")
    return real


validate_path_jail = resolve_in_root


def is_basename_safe(name: str) -> bool:
    """New file/folder names must be plain basenames (no separators/traversal)."""
    if not name or not name.strip():
        return False
    n = name.strip()
    if n in (".", ".."):
        return False
    if "/" in n or "\\" in n:
        return False
    if ".." in n:
        return False
    if len(n) > 255:
        return False
    stem = n.split(".")[0].lower()
    if stem in _WIN_RESERVED_NAMES:
        return False
    return True


def is_system_location(path: str) -> bool:
    """True for OS-critical locations tools must never create/rename/delete."""
    try:
        p = os.path.realpath(os.path.abspath(path))
    except Exception:
        return True
    stripped = p.rstrip(os.sep)
    drive, tail = os.path.splitdrive(stripped)
    if not tail or tail == os.sep:
        return True  # drive root ('C:\\') or filesystem root ('/')
    if drive:
        parts = [x.lower() for x in tail.split(os.sep) if x]
        if parts and parts[0] in _SYSTEM_DIR_NAMES | {"system volume information", "$recycle.bin"}:
            return True
    else:
        parts = [x.lower() for x in stripped.split(os.sep) if x]
        if parts and parts[0] in ("etc", "bin", "sbin", "usr", "sys", "proc", "boot", "windows"):
            return True
    return False

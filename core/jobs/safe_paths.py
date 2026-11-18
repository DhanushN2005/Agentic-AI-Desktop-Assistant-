"""Shared path-safety helpers for the build-job subsystem.

Every place that reads or writes a file whose name came from an LLM plan or
reply must go through :func:`safe_join` so that traversal, absolute paths,
drive letters, UNC paths, reserved Windows device names and symlink escapes are
rejected uniformly.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator

# Directories that never hold project source code (dependencies, VCS, caches).
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".flexie_backups",
    ".idea", ".vscode", "dist", "build",
})

_WIN_RESERVED = {
    "con", "prn", "aux", "nul", "conin$", "conout$",
    *(f"com{i}" for i in range(0, 10)),
    *(f"lpt{i}" for i in range(0, 10)),
}
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_MAX_REL_LEN = 240


def safe_rel_error(rel: object) -> str | None:
    """Return a reason string if ``rel`` is not an acceptable relative file name."""
    if not isinstance(rel, str):
        return f"path must be a string, got {type(rel).__name__}"
    if not rel or not rel.strip():
        return "empty path"
    if len(rel) > _MAX_REL_LEN:
        return "path too long"
    if "\x00" in rel or any(ord(c) < 32 for c in rel):
        return "control characters in path"
    p = rel.strip()
    if p.startswith(("/", "\\")) or _DRIVE_RE.match(p) or p.startswith("~"):
        return f"absolute or drive-qualified path not allowed: {rel!r}"
    if ":" in p:
        return f"':' not allowed in path (drive letters / alternate streams): {rel!r}"
    parts = [x for x in re.split(r"[\\/]+", p) if x not in ("", ".")]
    if not parts:
        return "empty path"
    for part in parts:
        if part == "..":
            return f"parent traversal not allowed: {rel!r}"
        if part != part.rstrip(". ") or part.endswith((" ", ".")):
            return f"component with trailing dot/space not allowed: {part!r}"
        if part.split(".")[0].strip().lower() in _WIN_RESERVED:
            return f"reserved Windows device name: {part!r}"
        if any(ch in part for ch in '<>"|?*'):
            return f"illegal character in path component: {part!r}"
    return None


def is_safe_rel(rel: object) -> bool:
    return safe_rel_error(rel) is None


def safe_join(root: str, rel: object) -> str:
    """Resolve ``rel`` under ``root`` or raise ``ValueError``.

    The result is a real path (symlinks resolved) that is guaranteed to be inside
    the real path of ``root``.
    """
    err = safe_rel_error(rel)
    if err:
        raise ValueError(err)
    assert isinstance(rel, str)
    real_root = os.path.realpath(os.path.abspath(root))
    parts = [x for x in re.split(r"[\\/]+", rel.strip()) if x not in ("", ".")]
    real = os.path.realpath(os.path.join(real_root, *parts))
    try:
        inside = os.path.commonpath([os.path.normcase(real), os.path.normcase(real_root)]) == os.path.normcase(real_root)
    except ValueError:
        inside = False
    if not inside or os.path.normcase(real) == os.path.normcase(real_root):
        raise ValueError(f"path escapes workspace root: {rel!r}")
    return real


def prune_dirs(dirs: list[str]) -> None:
    """In-place prune for ``os.walk`` so dependency/VCS dirs are never descended."""
    dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.lower().endswith(".egg-info")]


def iter_source_files(
    root: str, exts: Iterable[str] | None = None
) -> Iterator[tuple[str, str]]:
    """Yield ``(abs_path, rel_path)`` for project files, pruning dependency dirs."""
    ext_t = tuple(e.lower() for e in exts) if exts else None
    for cur, dirs, files in os.walk(root):
        prune_dirs(dirs)
        for f in files:
            if ext_t and not f.lower().endswith(ext_t):
                continue
            full = os.path.join(cur, f)
            try:
                rel = os.path.relpath(full, root)
            except ValueError:
                continue
            yield full, rel


def count_source_files(root: str) -> int:
    return sum(1 for _ in iter_source_files(root))


def rel_inside(candidate: str, root: str) -> str | None:
    """Return ``candidate`` relative to ``root`` if it is a file inside the source tree.

    Handles cross-drive paths (ValueError from ``relpath``), ``..`` escapes and
    files that live inside pruned dependency directories. Returns None otherwise.
    """
    if not candidate or not isinstance(candidate, str):
        return None
    try:
        cand = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
        real = os.path.realpath(cand)
        real_root = os.path.realpath(root)
        rel = os.path.relpath(real, real_root)
    except (ValueError, OSError):
        return None
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    if {p.lower() for p in re.split(r"[\\/]+", rel)} & SKIP_DIRS:
        return None
    if "site-packages" in rel.lower():
        return None
    if not os.path.isfile(real):
        return None
    return rel


def find_by_basename(root: str, base: str) -> str | None:
    """Find a file by basename inside the pruned source tree (relative path)."""
    if not base or base != os.path.basename(base):
        return None
    for cur, dirs, files in os.walk(root):
        prune_dirs(dirs)
        if base in files:
            try:
                return os.path.relpath(os.path.join(cur, base), root)
            except ValueError:
                return None
    return None


def atomic_write(path: str, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file + os.replace (never leaves a half file)."""
    import tempfile

    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".flexie_tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

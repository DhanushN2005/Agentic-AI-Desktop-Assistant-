"""Workspace path jail — fail-closed path validation for file tools.

``resolve_in_root(path, root)`` resolves ``path`` (relative → joined to
``root``) through symlinks via ``os.path.realpath`` and requires the result
to stay inside ``root`` (checked with ``os.path.commonpath``). Anything else
— ``..`` escapes, absolute paths outside the root, symlink escapes —
raises ``ValueError``.
"""
import os
import re

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
    reject_unsafe_syntax(p)
    for part in os.path.normpath(p).split(os.sep):
        if part:
            stem = part.split(".")[0].lower()
            if stem in _WIN_RESERVED_NAMES:
                raise ValueError(f"reserved Windows device name in path: {part!r}")
    if p.startswith(("\\\\", "//")):
        raise ValueError(f"UNC/network paths are not allowed: {p!r}")  # also avoids a network lookup
    joined = p if os.path.isabs(p) else os.path.join(root, p)
    try:
        real = os.path.realpath(os.path.abspath(joined))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot resolve path {p!r}: {exc}") from exc
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


# --------------------------------------------------------------------------------------
# Protected-path policy (TL-1 / TL-18)
#
# The jail root is the whole project folder, which also holds the source code, the git
# hooks, the MCP server list and the secrets. File TOOLS (model-driven) therefore use
# ``resolve_for_read`` / ``resolve_for_write``: same jail, plus a deny policy.
# --------------------------------------------------------------------------------------
_WRITE_DENY_TOP_DIRS = frozenset({
    "core", "sandbox", "skills", "verification", "supervisor", "runtime", "utils", "interface",
    "extension", "tests", "plugins", "engines", "agents", "adapters", "evals", "voice", "vision",
    "tools", "sdd", "recovery", "context", "templates", "flexie_web", "browser_session",
})
_WRITE_DENY_ANY_DIRS = frozenset({
    ".git", ".github", ".githooks", ".vscode", ".idea", ".claude", ".freebuff", "__pycache__",
    ".ssh", ".gnupg", ".aws",
})
_WRITE_DENY_TOP_EXT = frozenset({
    ".py", ".pyw", ".bat", ".cmd", ".ps1", ".vbs", ".sh", ".toml", ".cfg", ".ini", ".pth", ".spec",
    ".db", ".sqlite", ".sqlite3",
})
_WRITE_DENY_NAMES = frozenset({
    "conftest.py", "sitecustomize.py", "usercustomize.py", "setup.py", "pyproject.toml",
    "mcp_servers.json", "package.json", ".gitignore", ".gitattributes", ".gitmodules",
})
_SECRET_NAME_RE = re.compile(
    r"(^|[._\-\s])(tokens?|secrets?|credentials?|passwords?|passwd|apikeys?|api[_-]key)([._\-\s]|$)",
    re.IGNORECASE,
)
_SECRET_EXT = frozenset({".pem", ".key", ".pfx", ".p12", ".ppk", ".keystore", ".jks", ".kdbx"})
_SECRET_FILES = frozenset({
    ".netrc", "_netrc", ".git-credentials", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".npmrc", ".pypirc", ".htpasswd",
})
_SOURCE_EXT_OK_TO_READ = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".rst", ".html", ".css", ".java", ".c", ".h",
    ".cpp", ".go", ".rs", ".cs",
})
_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.\\", "//?/", "//./")


def reject_unsafe_syntax(p: str) -> None:
    """Reject NUL/control characters, device-namespace prefixes and NTFS alternate streams."""
    if "\x00" in p or any(ord(c) < 32 for c in p):
        raise ValueError("path contains control characters")
    if p.startswith(_DEVICE_PREFIXES):
        raise ValueError(f"device/extended-length paths are not allowed: {p!r}")
    rest = p
    m = re.match(r"^[A-Za-z]:", p)
    if m:
        rest = p[2:]
    if ":" in rest:
        raise ValueError(
            f"':' is not allowed in a path component (NTFS alternate data stream?): {p!r}"
        )


def _clean_component(part: str) -> str:
    """Windows ignores trailing dots/spaces; classify on the form the OS will actually use."""
    return part.rstrip(" .").lower() if part not in (".", "..") else part


def _long_path(real: str) -> str:
    """Expand 8.3 short names (``GIT~1``) on Windows so deny rules see the long name."""
    if os.name != "nt" or "~" not in real:
        return real
    try:
        import ctypes
        probe = real
        tail: list[str] = []
        while probe and not os.path.exists(probe):
            head, last = os.path.split(probe)
            if head == probe:
                break
            tail.append(last)
            probe = head
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetLongPathNameW(probe, buf, 1024)  # type: ignore[attr-defined]
        if 0 < n < 1024:
            probe = buf.value
        return os.path.join(probe, *reversed(tail)) if tail else probe
    except Exception:
        return real


def _is_secret_name(name: str, *, for_read: bool) -> bool:
    n = name.lower()
    stem, ext = os.path.splitext(n)
    if n.startswith(".env") or n == "env" or n in _SECRET_FILES or ext in _SECRET_EXT:
        return True
    if _SECRET_NAME_RE.search(n):
        if for_read and ext in _SOURCE_EXT_OK_TO_READ:
            return False
        return True
    return False


def resolve_protected(path: str, root: str, mode: str = "read") -> str:
    """Jail ``path`` inside ``root`` and apply the protected-path policy.

    ``mode`` is ``"read"`` (secrets denied) or ``"write"`` (secrets, VCS, source and control
    surface denied). Raises ``ValueError`` with an actionable message.
    """
    real = _long_path(resolve_in_root(path, root))
    real_root = _long_path(os.path.realpath(os.path.abspath(root)))
    rel = os.path.relpath(real, real_root)
    parts = [] if rel == "." else [_clean_component(x) for x in re.split(r"[\\/]+", rel) if x]
    if not parts:
        if mode == "write":
            raise ValueError("cannot write to the project root itself; use a file under 'workspace/'")
        return real
    shown = "/".join(parts)
    leaf = parts[-1]
    if _is_secret_name(leaf, for_read=(mode == "read")):
        raise ValueError(f"access to secret/credential file '{shown}' is blocked ({mode})")
    # Credential-bearing git config can be read by neither mode.
    if ".git" in parts and leaf in ("config", "credentials", "hooks"):
        raise ValueError(f"access to '{shown}' is blocked (git credentials / hooks)")
    if mode != "write":
        return real
    deny_any = _WRITE_DENY_ANY_DIRS.intersection(parts)
    if deny_any:
        raise ValueError(
            f"writes under '{sorted(deny_any)[0]}/' are blocked (VCS/editor/control surface); "
            "write inside 'workspace/' instead"
        )
    if parts[0] in _WRITE_DENY_TOP_DIRS:
        raise ValueError(
            f"writes under '{parts[0]}/' are blocked (source/control surface); "
            "write inside 'workspace/' instead"
        )
    if leaf in _WRITE_DENY_NAMES:
        raise ValueError(f"writing '{leaf}' is blocked (it can change what runs next); use 'workspace/'")
    if len(parts) == 1 and os.path.splitext(leaf)[1] in _WRITE_DENY_TOP_EXT:
        raise ValueError(
            f"writing '{shown}' in the project root is blocked (source/config); use 'workspace/'"
        )
    if leaf.endswith((".pth", ".pyc")) or leaf in ("package.json",):
        raise ValueError(f"writing '{leaf}' is blocked; use a different name or 'workspace/'")
    return real


def resolve_for_read(path: str, root: str | None = None) -> str:
    return resolve_protected(path, root or project_root(), "read")


def resolve_for_write(path: str, root: str | None = None) -> str:
    return resolve_protected(path, root or project_root(), "write")

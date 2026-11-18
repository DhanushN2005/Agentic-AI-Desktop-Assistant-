"""
Coding Tools Registry — registers autonomous coding tools into ToolRegistry.

Wired by FlexieOrchestrator after ToolRegistry creation.
All tools return ActionResult and go through PermissionSystem + Verification.

Security model (TL-1/2/10/11/12/13):
  * file tools use the protected-path jail from ``utils.path_jail`` (secrets unreadable,
    source/control surface unwritable, NTFS streams/8.3/trailing-dot tricks normalised);
  * terminal.run has a per-binary subcommand/flag policy, quote-aware parsing, no shell,
    one global deadline and runs in the project root;
  * git/test/search tools run with cwd=project_root().
"""
import codecs
import functools
import json
import logging
import os
import re
import subprocess
import sys
import time
from itertools import islice
from pathlib import Path

from core.action_result import ActionResult
from core.safety import SafetyGuard
from core.tool_registry import PermissionLevel, ToolRegistry, ToolSchema, ToolSpec
from utils.config import Config
from utils.path_jail import (
    _is_secret_name,
    project_root,
    resolve_protected,
)

MAX_FILE_BYTES = 2 * 1024 * 1024        # read/write/patch size cap (2 MB)
MAX_READ_CHARS = 200_000                # cap on what one file.read returns
MAX_DIFF_CHARS = 16_000                 # cap on git.diff full output
_MAX_TERMINAL_TIMEOUT = 120             # hard cap — LLM cannot request unbounded runs
_TERMINAL_OUT_CHARS = 6000
_TEST_OUT_CHARS = 5000


def _jailed(path: str) -> str:
    """Resolve a tool path for READING inside the project workspace (raises ValueError)."""
    return resolve_protected(path, project_root(), "read")


def _jailed_write(path: str) -> str:
    """Resolve a tool path for WRITING (raises ValueError for protected locations)."""
    return resolve_protected(path, project_root(), "write")


def _tail(text: str, limit: int) -> str:
    """Tail-biased truncation: errors and summary lines live at the END of the output."""
    if len(text) <= limit:
        return text
    cut = len(text) - limit
    return f"[... {cut} chars truncated ...]\n" + text[-limit:]


def _head(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... {len(text) - limit} chars truncated ...]"


# ----------------------------------------------------------------------------- text I/O helpers
def _decode_file(raw: bytes) -> tuple[str, str]:
    """Decode like file.read does (UTF-8, BOM aware) but fall back to latin-1 without loss."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise ValueError("UTF-16 files are not supported by file.patch")
    if b"\x00" in raw:
        raise ValueError("binary file; refusing to patch")
    try:
        text = raw.decode("utf-8-sig")
        return text, ("utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else "utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _dominant_eol(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _with_eol(snippet: str, eol: str) -> str:
    snippet = snippet.replace("\r\n", "\n")
    return snippet.replace("\n", "\r\n") if eol == "\r\n" else snippet


# ----------------------------------------------------------------------------- binaries / PATH
@functools.lru_cache(maxsize=64)
def _which(name: str) -> str | None:
    """Resolve a binary on PATH WITHOUT the current directory (Windows searches cwd first)."""
    exts = [""]
    if os.name == "nt":
        exts = [e.lower() for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    root = os.path.normcase(os.path.realpath(project_root()))
    cwd = os.path.normcase(os.path.realpath(os.getcwd()))
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        nd = os.path.normcase(os.path.realpath(d))
        if nd in (root, cwd):
            continue
        for ext in exts:
            cand = os.path.join(d, name + ext)
            if os.path.isfile(cand):
                return cand
    return None


# ----------------------------------------------------------------------------- terminal policy
class _Denied(Exception):
    """A terminal segment violates the per-binary policy."""


_TERMINAL_ALLOWLIST = frozenset({
    "git", "python", "python3", "py", "pytest", "ruff", "node", "npm", "tsc",
    "echo", "pwd", "cd", "ls", "dir", "tree", "where", "which", "mkdir",
})

_GIT_COMMON_NOFLAGS = r"--"
_GIT_FLAGS = {
    "status": r"-s|--short|-b|--branch|--porcelain(=v[12])?|--long|-z|--ignored|-u(no|normal|all)|"
              r"--untracked-files(=(no|normal|all))?",
    "diff": r"--stat(=[\d,]+)?|--name-only|--name-status|--cached|--staged|--shortstat|--numstat|"
            r"--no-color|--color=never|-w|--ignore-all-space|-U\d+|--unified=\d+|--check|--summary|"
            r"-p|--patch|--compact-summary|--no-ext-diff|--no-textconv|--minimal|--histogram|"
            r"--patience|--raw|-R|--",
    "log": r"--oneline|-n\d*|-\d+|--stat|--name-only|--name-status|--graph|--decorate|--no-decorate|"
           r"--no-color|--pretty=(oneline|short|medium|full|fuller|reference)|--format=\S*|"
           r"--since=.*|--until=.*|--author=.*|--grep=.*|--all|--reverse|--max-count=\d+|-p|--patch|"
           r"--shortstat|--no-merges|--merges|--first-parent|-n|--",
    "show": r"--stat|--name-only|--name-status|--no-color|--pretty=(oneline|short|medium|full|fuller)|"
            r"--format=\S*|-p|--patch|--shortstat|--no-patch|-s|--oneline|-U\d+|--",
    "branch": r"-a|--all|-r|--remotes|-v|-vv|--verbose|--show-current|--list|--contains|--merged|"
              r"--no-merged",
    "rev-parse": r"--short(=\d+)?|--abbrev-ref|--show-toplevel|--is-inside-work-tree|--verify|"
                 r"--symbolic-full-name|--git-dir",
    "add": r"--|-v|--verbose|-n|--dry-run",
    "commit": r"-m|--message=.*|-m.+|--no-edit|--amend|-q|--quiet|-s|--signoff|--allow-empty",
}
_GIT_FLAG_RE = {k: re.compile(rf"^(?:{v})$") for k, v in _GIT_FLAGS.items()}
_ABS_OR_DRIVE_RE = re.compile(r"^(?:[A-Za-z]:|[\\/]|~)")
_BARE_NAME_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")
_SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9_:.-]+$")


def _plain_arg(arg: str) -> None:
    """Reject arguments that point outside the project (absolute, drive, UNC, ``..``, ``~``)."""
    if "\x00" in arg:
        raise _Denied("NUL in argument")
    if _ABS_OR_DRIVE_RE.match(arg):
        raise _Denied(f"absolute/drive/home path argument not allowed: {arg!r}")
    if any(part == ".." for part in re.split(r"[\\/]+", arg)):
        raise _Denied(f"'..' not allowed in argument: {arg!r}")


def _jail_arg(arg: str, root: str, mode: str = "read") -> str:
    try:
        return resolve_protected(arg, root, mode)
    except ValueError as exc:
        raise _Denied(str(exc)) from exc


def _git_ref_arg(arg: str, root: str) -> None:
    """A non-flag git argument: revision or path. No escapes, no secret files."""
    if arg.startswith("-"):
        raise _Denied(f"unexpected option {arg!r}")
    _plain_arg(arg)
    leaf_src = arg.rsplit(":", 1)[-1]
    leaf = re.split(r"[\\/]+", leaf_src)[-1].rstrip(" .")
    if leaf and _is_secret_name(leaf, for_read=True):
        raise _Denied(f"git argument names a secret/credential file: {arg!r}")


def _git_policy(args: list[str], root: str) -> list[str]:
    if not args:
        raise _Denied("git needs a subcommand (status, diff, log, add, commit, branch, show, rev-parse)")
    sub = args[0]
    rest = args[1:]
    if sub not in _GIT_FLAG_RE:
        raise _Denied(
            f"git subcommand/option {sub!r} is not allowed; allowed: "
            f"{', '.join(sorted(_GIT_FLAG_RE))} (no -c, push/fetch/clone/config...)"
        )
    flag_re = _GIT_FLAG_RE[sub]
    out: list[str] = [sub]
    i = 0
    paths_only = False
    positional: list[str] = []
    while i < len(rest):
        a = rest[i]
        if paths_only or not a.startswith("-") or a == "-":
            if sub == "commit":
                raise _Denied("git commit takes no pathspecs here; stage with git add <files> first")
            _git_ref_arg(a, root)
            positional.append(a)
            out.append(a)
            i += 1
            continue
        if a == "--":
            paths_only = True
            out.append(a)
            i += 1
            continue
        if not flag_re.match(a):
            raise _Denied(f"git {sub}: option {a!r} is not allowed")
        out.append(a)
        if sub == "commit" and a == "-m":
            if i + 1 >= len(rest):
                raise _Denied("git commit -m needs a message")
            out.append(rest[i + 1])  # the message is data, whatever it starts with
            i += 2
            continue
        i += 1
    if sub == "add":
        if not positional:
            raise _Denied("git add needs explicit file paths (use the git.commit tool to stage everything safely)")
        for p in positional:
            real = _jail_arg(p, root, "read")
            if os.path.isdir(real) or p in (".", "./"):
                raise _Denied("git add of a directory/'.' is not allowed; list the files")
    elif sub in ("diff", "log", "show") and paths_only:
        for p in positional:
            _jail_arg(p, root, "read")
    return out


def _npm_policy(args: list[str], root: str) -> list[str]:
    if not args:
        raise _Denied("npm needs a subcommand: test | run <script> | ls")
    sub, rest = args[0], args[1:]
    safe_flags = {"--silent", "-s", "--quiet", "--no-progress"}
    if sub in ("test", "t"):
        if any(r not in safe_flags for r in rest):
            raise _Denied("npm test accepts only --silent/--quiet")
        return ["test", *rest]
    if sub in ("ls", "list"):
        for r in rest:
            if r not in safe_flags and not re.fullmatch(r"--depth=\d", r):
                raise _Denied(f"npm ls: option {r!r} is not allowed")
        return ["ls", *rest]
    if sub in ("run", "run-script"):
        names = [r for r in rest if not r.startswith("-")]
        flags = [r for r in rest if r.startswith("-")]
        if len(names) != 1 or any(f not in safe_flags for f in flags):
            raise _Denied("npm run takes exactly one script name (no '--' passthrough)")
        script = names[0]
        if not _SCRIPT_NAME_RE.match(script):
            raise _Denied(f"bad npm script name {script!r}")
        try:
            with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                scripts = (json.load(f) or {}).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        if script not in scripts:
            raise _Denied(f"npm script {script!r} is not defined in package.json")
        return ["run", script, *flags]
    raise _Denied(f"npm {sub!r} is not allowed (install/exec/publish/config run arbitrary code); use test | run | ls")


_PYTEST_FLAG_RE = re.compile(
    r"^(?:-q|-qq|-v|-vv|-x|-s|-l|--lf|--ff|--no-header|--tb=(short|long|line|no|native|auto)|"
    r"--maxfail=\d+|-r[A-Za-z]+|--durations=\d+|--collect-only|--co|--disable-warnings)$"
)
_PYTEST_VALUE_FLAGS = frozenset({"-k", "-m"})


def _pytest_policy(args: list[str], root: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in _PYTEST_VALUE_FLAGS:
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                raise _Denied(f"pytest {a} needs an expression")
            out += [a, args[i + 1]]
            i += 2
            continue
        if a.startswith("-"):
            if not _PYTEST_FLAG_RE.match(a):
                raise _Denied(f"pytest option {a!r} is not allowed (no -p/-c/--rootdir/-o)")
            out.append(a)
        else:
            target = a.split("::", 1)
            real = _jail_arg(target[0], root, "read")
            out.append(real + ("::" + target[1] if len(target) > 1 else ""))
        i += 1
    return [sys.executable, "-m", "pytest", *out]


_RUFF_FLAG_RE = re.compile(
    r"^(?:--check|--diff|--statistics|--no-cache|-q|--quiet|--output-format=(concise|full|json|grouped)|"
    r"--select=[A-Z0-9,]+|--ignore=[A-Z0-9,]+)$"
)


def _ruff_policy(args: list[str], root: str) -> list[str]:
    if not args or args[0] not in ("check", "format"):
        raise _Denied("ruff: only 'check' and 'format --check/--diff' are allowed")
    out = [args[0]]
    for a in args[1:]:
        if a.startswith("-"):
            if not _RUFF_FLAG_RE.match(a):
                raise _Denied(f"ruff option {a!r} is not allowed (no --fix/--config)")
            out.append(a)
        else:
            out.append(_jail_arg(a, root, "read"))
    if args[0] == "format" and not ({"--check", "--diff"} & set(out)):
        raise _Denied("ruff format must be run with --check or --diff")
    return [sys.executable, "-m", "ruff", *out]


def _script_policy(kind: str, args: list[str], root: str) -> list[str]:
    exts = (".py",) if kind == "python" else (".js", ".mjs", ".cjs")
    if not args:
        raise _Denied(f"{kind} must be given a project script file (interactive/stdin is not allowed)")
    first = args[0]
    if first.startswith("-"):
        raise _Denied(f"{kind} option {first!r} is not allowed (-c/-e/-m/--eval run arbitrary code); pass a script file")
    real = _jail_arg(first, root, "read")
    if not os.path.isfile(real) or not real.lower().endswith(exts):
        raise _Denied(f"{kind} may only run an existing {'/'.join(exts)} file inside the project: {first!r}")
    for extra in args[1:]:
        _plain_arg(extra)
    exe = sys.executable if kind == "python" else (_which("node") or "node")
    return [exe, real, *args[1:]]


def _listing_policy(args: list[str], root: str) -> list[str]:
    out: list[str] = []
    for a in args:
        if re.fullmatch(r"[-/][A-Za-z0-9]{1,3}", a):
            out.append(a)
        else:
            out.append(_jail_arg(a, root, "read"))
    return out


def _check_segment(argv: list[str], root: str) -> tuple[list[str] | None, str]:
    """Apply the per-binary policy. Returns (final argv, '') or (None, name) if not allowlisted.

    Raises ``_Denied`` when the binary is allowed but this invocation is not.
    """
    first = argv[0]
    if re.search(r"[\\/]", first) or ":" in first:
        raise _Denied(f"run binaries by bare name only, not by path: {first!r}")
    name = first.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in _TERMINAL_ALLOWLIST:
        return None, first
    args = argv[1:]
    if name == "git":
        return [_which("git") or "git", *_git_policy(args, root)], ""
    if name in ("python", "python3", "py"):
        return _script_policy("python", args, root), ""
    if name == "node":
        return _script_policy("node", args, root), ""
    if name == "pytest":
        return _pytest_policy(args, root), ""
    if name == "ruff":
        return _ruff_policy(args, root), ""
    if name == "npm":
        return [_which("npm") or "npm", *_npm_policy(args, root)], ""
    if name == "tsc":
        if args != ["--noEmit"]:
            raise _Denied("tsc is only allowed as 'tsc --noEmit'")
        return [_which("tsc") or "tsc", "--noEmit"], ""
    if name in ("where", "which"):
        if not args or not all(_BARE_NAME_RE.match(a) for a in args):
            raise _Denied(f"{name} accepts only bare program names")
        return [argv[0], *args], ""
    if name in ("ls", "dir", "tree"):
        return [argv[0], *_listing_policy(args, root)], ""
    if name in ("pwd",):
        return [argv[0]], ""
    if name == "cd":
        return [argv[0], *[_jail_arg(a, root, "read") for a in args]], ""
    if name == "mkdir":
        paths = [a for a in args if not a.startswith("-")]
        if len(paths) != len(args) and args != ["-p", *paths]:
            raise _Denied("mkdir accepts only paths (and -p)")
        for a in paths:
            _jail_arg(a, root, "write")
        return [argv[0], *args], ""
    return [argv[0], *args], ""  # echo: plain text only, no shell to interpret it


def _parse_command(command: str) -> tuple[list[list[str]], list[str]]:
    """Quote-aware split into argv segments and the chaining operators between them.

    Operators inside quotes are data. Pipes, redirections, single ``&``, newlines and
    unquoted command substitution are rejected (there is no shell to interpret them).
    Backslashes are literal (Windows paths); ``\\"`` inside double quotes is a quote.
    """
    segs: list[list[str]] = [[]]
    ops: list[str] = []
    tok: list[str] = []
    started = False

    def flush() -> None:
        nonlocal started
        if started:
            segs[-1].append("".join(tok))
            tok.clear()
            started = False

    i, n = 0, len(command)
    while i < n:
        c = command[i]
        if c in "\r\n\x00":
            raise ValueError("Newlines/control characters are not allowed in a command.")
        if c == "'":
            j = command.find("'", i + 1)
            if j < 0:
                raise ValueError("Unterminated single quote.")
            tok.append(command[i + 1:j])
            started = True
            i = j + 1
            continue
        if c == '"':
            i += 1
            while True:
                if i >= n:
                    raise ValueError("Unterminated double quote.")
                ch = command[i]
                if ch == '"':
                    i += 1
                    break
                if ch in "\r\n\x00":
                    raise ValueError("Newlines/control characters are not allowed in a command.")
                if ch == "\\" and i + 1 < n and command[i + 1] == '"':
                    tok.append('"')
                    i += 2
                    continue
                tok.append(ch)
                i += 1
            started = True
            continue
        if c in " \t":
            flush()
            i += 1
            continue
        two = command[i:i + 2]
        if two in ("&&", "||") or c == ";":
            flush()
            op = two if c != ";" else ";"
            ops.append(op)
            segs.append([])
            i += len(op)
            continue
        if c == "|":
            raise ValueError("Pipes (|) are not supported without a shell. Run steps separately.")
        if c in "<>":
            raise ValueError("Redirection (< >) is not supported. Use the file tools to write files.")
        if c == "&":
            raise ValueError("A single '&' is not supported; use '&&' to chain commands.")
        if c == "`" or two == "$(":
            raise ValueError("Command substitution (backticks / $()) is not allowed.")
        tok.append(c)
        started = True
        i += 1
    flush()
    return segs, ops


def register_coding_tools(registry: ToolRegistry, orch) -> int:
    """Register all coding-autonomy tools. Returns count registered."""
    logger = logging.getLogger("Flexie.CodingTools")
    count = 0

    # --- Helper fns closing over orch ---
    def _file_read(path: str, start_line: int = 1, end_line: int | None = None) -> ActionResult:
        try:
            abs_path = _jailed(path)
            if not os.path.exists(abs_path):
                return ActionResult.fail(message=f"File not found: {path}", intent="file.read")
            if not os.path.isfile(abs_path):
                return ActionResult.fail(message=f"Not a regular file: {path}", intent="file.read")
            start_line = max(1, int(start_line))
            if end_line is not None and end_line < start_line:
                return ActionResult.fail(message="end_line must be >= start_line", intent="file.read")
            if end_line is None and os.path.getsize(abs_path) > MAX_FILE_BYTES:
                return ActionResult.fail(
                    message=f"File is larger than {MAX_FILE_BYTES // 1024} KB; read it with start_line/end_line.",
                    intent="file.read",
                )
            with open(abs_path, encoding="utf-8-sig", errors="replace") as f:
                chosen = list(islice(f, start_line - 1, end_line))
            content = "".join(chosen)
            if len(content) > MAX_READ_CHARS:
                content = content[:MAX_READ_CHARS] + "\n[... truncated; request a smaller line range ...]"
            last = start_line + len(chosen) - 1 if chosen else start_line
            return ActionResult.ok(message=f"Read {path} lines {start_line}-{last}", intent="file.read",
                                   data={"content": content, "path": abs_path})
        except Exception as e:
            logging.debug("[core/coding_tools.py] file.read: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="file.read")

    def _file_write(path: str, content: str, mkdir: bool = True) -> ActionResult:
        try:
            abs_path = _jailed_write(path)
            if len(content) > MAX_FILE_BYTES or (
                len(content) > MAX_FILE_BYTES // 4 and len(content.encode("utf-8", "surrogatepass")) > MAX_FILE_BYTES
            ):
                return ActionResult.fail(message=f"Content exceeds the {MAX_FILE_BYTES // 1024} KB write limit",
                                         intent="file.write")
            if os.path.isdir(abs_path):
                return ActionResult.fail(message=f"Path is a directory: {path}", intent="file.write")
            if mkdir:
                os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            # log to memory
            try:
                if hasattr(orch, 'memory_manager') and orch.memory_manager:
                    from core.memory_manager import MemoryCategory
                    orch.memory_manager.remember(f"write:{os.path.basename(path)}", f"Wrote {path} ({len(content)} chars)", MemoryCategory.TASKS, importance=0.5, tags=["code","write"])
            except Exception as _e:
                logging.debug("[core/coding_tools.py] memory log: %s: %s", type(_e).__name__, _e)
            return ActionResult.ok(message=f"Wrote {path} ({len(content)} chars)", intent="file.write", data={"path": abs_path})
        except Exception as e:
            logging.debug("[core/coding_tools.py] file.write: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="file.write")

    def _file_patch(path: str, original: str, replacement: str, expected_count: int = 1) -> ActionResult:
        try:
            if not isinstance(expected_count, int) or isinstance(expected_count, bool) or not 1 <= expected_count <= 20:
                return ActionResult.fail(message="expected_count must be between 1 and 20", intent="file.patch")
            if not original:
                return ActionResult.fail(message="'original' snippet must not be empty", intent="file.patch")
            abs_path = _jailed_write(path)
            if not os.path.exists(abs_path):
                return ActionResult.fail(message=f"File not found: {path}", intent="file.patch")
            if os.path.getsize(abs_path) > MAX_FILE_BYTES:
                return ActionResult.fail(message=f"File exceeds the {MAX_FILE_BYTES // 1024} KB patch limit",
                                         intent="file.patch")
            with open(abs_path, "rb") as f:
                content, enc = _decode_file(f.read())
            eol = _dominant_eol(content)
            needle = original
            found = content.count(needle)
            if found == 0:
                needle = _with_eol(original, eol)  # snippet CRLF/LF differs from the file's
                found = content.count(needle)
            if found == 0:
                return ActionResult.fail(message="Original snippet not found in file", intent="file.patch", data={"found": 0})
            if found != expected_count:
                return ActionResult.fail(message=f"Expected {expected_count} occurrence(s) but found {found} - ambiguous patch", intent="file.patch")
            new_content = content.replace(needle, _with_eol(replacement, eol))
            with open(abs_path, "w", encoding=enc, newline="") as f:  # newline='' keeps every line ending
                f.write(new_content)
            return ActionResult.ok(message=f"Patched {path} ({found} replacement)", intent="file.patch", data={"path": abs_path})
        except Exception as e:
            logging.debug("[core/coding_tools.py] file.patch: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="file.patch")

    def _code_search(query: str, max_results: int = 20) -> ActionResult:
        try:
            from engines.code_search import CodeSearchEngine
            root = project_root()
            engine = CodeSearchEngine(workspace_path=root)
            res = engine.search(query, max_results=max_results)
            safe = []
            for m in res.matches:  # never surface lines from secret files (.env, tokens, keys)
                try:
                    resolve_protected(m.file, root, "read")
                except ValueError:
                    continue
                safe.append(m)
            summary = "\n".join([f"{m.file}:{m.line_start} | {m.content[:120]}" for m in safe[:10]])
            return ActionResult.ok(message=f"Found {len(safe)} matches for '{query}'", intent="code.search", data={"matches": [m.to_dict() for m in safe], "summary": summary})
        except Exception as e:
            logging.debug("[core/coding_tools.py] code.search: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="code.search")

    def _git(args: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", GIT_OPTIONAL_LOCKS="0")
        return subprocess.run(
            [_which("git") or "git", *args], cwd=project_root(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL,
        )

    def _git_out(args: list[str], timeout: float = 10) -> str:
        proc = _git(args, timeout)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"git {args[0]} failed").strip()[:500])
        return proc.stdout

    def _git_toplevel_ok() -> str | None:
        """None when git's toplevel IS the project root; otherwise an error message."""
        top = _git_out(["rev-parse", "--show-toplevel"]).strip()
        a = os.path.normcase(os.path.realpath(top))
        b = os.path.normcase(os.path.realpath(project_root()))
        if a != b:
            return f"git repository root ({top}) is not the project root; refusing to touch another repo"
        return None

    def _git_status() -> ActionResult:
        try:
            out = _git_out(["status", "--short"])
            if not out.strip():
                return ActionResult.ok(message="Git repo clean", intent="git.status", data={"output": out})
            return ActionResult.ok(message="Git status retrieved", intent="git.status", data={"output": _head(out, MAX_DIFF_CHARS)})
        except Exception as e:
            logging.debug("[core/coding_tools.py] git.status: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="git.status")

    def _git_diff(stat_only: bool = True) -> ActionResult:
        try:
            out = _git_out(["diff", "--stat"] if stat_only else ["diff"])
            return ActionResult.ok(message="Git diff retrieved", intent="git.diff",
                                   data={"output": _head(out, MAX_DIFF_CHARS) if out else "(no diff)"})
        except Exception as e:
            logging.debug("[core/coding_tools.py] git.diff: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="git.diff")

    def _secret_paths_staged() -> list[str]:
        raw = _git_out(["diff", "--cached", "--name-only", "-z"])
        return [p for p in raw.split("\0") if p and _is_secret_name(re.split(r"[\\/]", p)[-1].rstrip(" ."), for_read=False)]

    def _stage_all_safely() -> int:
        """``git add -A`` minus secrets: stage only paths that pass the secret-name policy."""
        raw = _git_out(["status", "--porcelain", "-z", "--untracked-files=all"])
        entries = raw.split("\0")
        paths: list[str] = []
        i = 0
        while i < len(entries):
            e = entries[i]
            i += 1
            if len(e) < 4:
                continue
            xy, path = e[:2], e[3:]
            if xy[0] in "RC":
                i += 1  # skip the original name of a rename/copy
            leaf = re.split(r"[\\/]", path)[-1].rstrip(" .")
            parts = [p.rstrip(" .").lower() for p in re.split(r"[\\/]", path)]
            if _is_secret_name(leaf, for_read=False) or ".git" in parts:
                continue
            paths.append(path)
        for k in range(0, len(paths), 100):
            _git_out(["add", "-A", "--", *paths[k:k + 100]])
        return len(paths)

    def _git_commit(message: str, add_all: bool = True) -> ActionResult:
        try:
            if not message or not message.strip():
                return ActionResult.fail(message="Commit message must not be empty", intent="git.commit")
            problem = _git_toplevel_ok()
            if problem:
                return ActionResult.fail(message=problem, intent="git.commit")
            if add_all:
                _stage_all_safely()
            staged_secrets = _secret_paths_staged()
            if staged_secrets:
                return ActionResult.fail(
                    message="Refusing to commit secret/credential files: " + ", ".join(staged_secrets[:5])
                            + ". Unstage them with `git restore --staged <file>`.",
                    intent="git.commit",
                )
            _git_out(["commit", "-m", message], timeout=30)
            return ActionResult.ok(message=f"Committed: {message}", intent="git.commit")
        except Exception as e:
            logging.debug("[core/coding_tools.py] git.commit: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=f"Git commit failed: {e}", intent="git.commit")

    # Binaries the terminal tool may invoke. Deliberately EXCLUDED: OS-destructive commands,
    # remote-exec primitives, generic launchers, package installers/runners (npx, pip),
    # and tools whose flags execute code or read arbitrary files (rg --pre, robocopy, cat/type).
    # Each allowed binary has a subcommand/flag policy (see _check_segment).

    def _terminal_run(command: str, timeout: int = 15) -> ActionResult:
        # Fail CLOSED: if validation can't run, the command does not run.
        if not SafetyGuard().validate(command):
            return ActionResult.fail(message="Blocked by SafetyGuard", intent="terminal.run")
        try:
            segments, operators = _parse_command(command)  # parsed ONCE
        except ValueError as e:
            return ActionResult.fail(message=str(e), intent="terminal.run")
        root = project_root()
        plan: list[list[str]] = []
        for seg in segments:
            if not seg:
                plan.append([])
                continue
            try:
                final, bad = _check_segment(seg, root)
            except _Denied as e:
                return ActionResult.fail(message=f"Command not allowed: {e}", intent="terminal.run")
            if final is None:
                return ActionResult.fail(
                    message=f"Binary '{bad}' is not on the terminal allowlist. "
                            f"Allowed: {', '.join(sorted(_TERMINAL_ALLOWLIST))}",
                    intent="terminal.run",
                )
            plan.append(final)
        if not any(plan):
            return ActionResult.fail(message="Empty command", intent="terminal.run")
        timeout = min(max(1, int(timeout)), _MAX_TERMINAL_TIMEOUT)
        deadline = time.monotonic() + timeout  # ONE deadline for the whole chain
        combined: list[str] = []
        last_code = 0
        # operators[i] chains segments[i] -> segments[i+1]:
        # '&&' run next only if ok, '||' only if failed, ';' always.
        pending_op: str | None = None
        try:
            for idx, argv in enumerate(plan):
                if not argv:
                    pending_op = operators[idx] if idx < len(operators) else None
                    continue
                if pending_op == "&&" and last_code != 0:
                    pending_op = operators[idx] if idx < len(operators) else None
                    continue
                if pending_op == "||" and last_code == 0:
                    pending_op = operators[idx] if idx < len(operators) else None
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ActionResult.fail(message=f"Timeout after {timeout}s", intent="terminal.run",
                                             data={"output": _tail("\n".join(combined), _TERMINAL_OUT_CHARS)})
                proc = subprocess.run(
                    argv, shell=False, capture_output=True, text=True, timeout=remaining,
                    cwd=root, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                )
                out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
                out = out.strip()
                if out:
                    combined.append(out)
                last_code = proc.returncode
                pending_op = operators[idx] if idx < len(operators) else None
            text = _tail("\n".join(combined).strip(), _TERMINAL_OUT_CHARS)
            if last_code == 0:
                return ActionResult.ok(message="Command succeeded", intent="terminal.run", data={"output": text, "returncode": 0})
            return ActionResult.fail(message=f"Command failed (exit {last_code})", intent="terminal.run", data={"output": text, "returncode": last_code})
        except subprocess.TimeoutExpired as _e:
            logging.debug("[core/coding_tools.py] terminal timeout: %s", _e)
            return ActionResult.fail(message=f"Timeout after {timeout}s", intent="terminal.run")
        except FileNotFoundError as _e:
            logging.debug("[core/coding_tools.py] terminal not found: %s", _e)
            return ActionResult.fail(message=f"Binary not found: {_e}", intent="terminal.run")
        except Exception as e:
            logging.debug("[core/coding_tools.py] terminal: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="terminal.run")

    _OPENABLE_EXT = frozenset({".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".txt", ".md"})

    def _app_open(path: str) -> ActionResult:
        """Open a local file (HTML/PDF/image) in the system browser or default app."""
        try:
            abs_path = _jailed(path)
            if not os.path.exists(abs_path):
                return ActionResult.fail(message=f"File not found: {path}", intent="app.open")
            if os.path.splitext(abs_path)[1].lower() not in _OPENABLE_EXT:
                return ActionResult.fail(message="Only HTML/PDF/image/text files can be opened", intent="app.open")
            import webbrowser
            url = Path(abs_path).as_uri()
            if not orch.voice.confirm(f"Created {os.path.basename(path)}. Open it in your browser?"):
                return ActionResult.ok(message="User declined to open", intent="app.open")
            opened = webbrowser.open(url)
            if opened:
                return ActionResult.ok(message=f"Opened {path} in browser", intent="app.open")
            return ActionResult.fail(message=f"Could not open {path}", intent="app.open")
        except Exception as e:
            logging.debug("[core/coding_tools.py:app_open] Swallowed exception: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="app.open")

    def _test_run(path: str = "tests/", verbose: bool = False) -> ActionResult:
        try:
            if path.strip().startswith("-"):
                return ActionResult.fail(message="test path must not start with '-' (no pytest options)", intent="test.run")
            root = project_root()
            real = _jailed(path)
            if not os.path.exists(real):
                return ActionResult.fail(message=f"Test path not found: {path}", intent="test.run")
            cmd = [sys.executable, "-m", "pytest", real, "-v" if verbose else "-q"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=root,
                                  stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
            out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            out = _tail(out.strip(), _TEST_OUT_CHARS)  # keep the TAIL: the summary line is last
            if proc.returncode == 0:
                return ActionResult.ok(message="Tests passed", intent="test.run", data={"output": out})
            return ActionResult.fail(message="Tests failed", intent="test.run", data={"output": out, "returncode": proc.returncode})
        except Exception as e:
            logging.debug("[core/coding_tools.py] test.run: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="test.run")

    def _python_exec(code: str, timeout: int = 15) -> ActionResult:
        # Isolation is an operator POLICY, never a model-supplied argument: the LLM
        # cannot opt out of the sandbox. Host execution requires the explicit
        # FLEXIE_ALLOW_UNSANDBOXED_EXEC=1 environment setting.
        use_sandbox = os.getenv("FLEXIE_ALLOW_UNSANDBOXED_EXEC", "0") != "1"
        timeout = min(max(1, int(timeout)), _MAX_TERMINAL_TIMEOUT)
        try:
            if use_sandbox:
                from sandbox.executor import SandboxExecutor
                allow_fallback = getattr(Config, "ALLOW_HOST_FALLBACK", False)
                ex = SandboxExecutor(timeout=timeout, allow_host_fallback=allow_fallback)
                ok, out = ex.run_python_code_ex(code)  # structured result, no substring sniffing
                if not ok:
                    return ActionResult.fail(message=out[:2000], intent="python.exec", data={"output": out})
                return ActionResult.ok(message="Python exec succeeded", intent="python.exec", data={"output": _tail(out, 4000)})
            else:
                proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                      timeout=timeout, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
                out = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode == 0:
                    return ActionResult.ok(message="Python exec succeeded", intent="python.exec", data={"output": _tail(out, 4000)})
                return ActionResult.fail(message=_tail(out, 2000), intent="python.exec")
        except Exception as e:
            logging.debug("[core/coding_tools.py] python.exec: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="python.exec")

    def _project_explain() -> ActionResult:
        try:
            if hasattr(orch, 'dev'):
                msg = orch.dev.explain_project()
                return ActionResult.ok(message=msg, intent="project.explain", data={"output": msg})
            return ActionResult.fail(message="DeveloperEngine not available", intent="project.explain")
        except Exception as e:
            logging.debug("[core/coding_tools.py] project.explain: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="project.explain")

    # --- Register specs ---
    S = ToolSchema
    specs = [
        ToolSpec(name="file.read", capabilities=["filesystem:read"], description="Read a file with optional line range (autonomous coding). Secrets (.env, tokens, keys) are unreadable.", params=[S("path", "str", True, description="Relative or absolute file path inside the project", max_length=1024), S("start_line", "int", False, 1, "Start line (>=1)", minimum=1, maximum=10_000_000), S("end_line", "int", False, None, "End line", minimum=1, maximum=10_000_000)], permission=PermissionLevel.READ_ONLY, execute_fn=_file_read, timeout=5, tags=["file","code"], error_strategy="abort", idempotent=True),
        ToolSpec(name="file.write", capabilities=["filesystem:read", "filesystem:write"], description="Write/create a file (creates dirs). Writable area: workspace/ (source dirs, .git, .env, config are protected). Max 2 MB.", params=[S("path", "str", True, description="Target file path, e.g. workspace/app.py", max_length=1024), S("content", "str", True, description="Full file content", max_length=MAX_FILE_BYTES), S("mkdir", "bool", False, True, "Create parent dirs")], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_file_write, timeout=10, tags=["file","code"], error_strategy="retry", idempotent=True),
        ToolSpec(name="app.open", capabilities=["network:fetch"], description="Open a local file (HTML/PDF/image) in the browser. Asks user first.", params=[S("path", "str", True, description="File path to open", max_length=1024)], permission=PermissionLevel.SAFE_ACTION, execute_fn=_app_open, timeout=10, tags=["app","browser"], error_strategy="abort"),
        ToolSpec(name="file.patch", capabilities=["filesystem:read", "filesystem:write"], description="Surgical patch: replace exact original snippet with replacement in file (line endings preserved)", params=[S("path", "str", True, max_length=1024), S("original", "str", True, description="Exact snippet to replace", max_length=200_000), S("replacement", "str", True, max_length=200_000), S("expected_count", "int", False, 1, "Expected occurrences (1-20)", minimum=1, maximum=20)], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_file_patch, timeout=8, tags=["file","code"], error_strategy="abort", idempotent=False),
        ToolSpec(name="code.search", idempotent=True, capabilities=["filesystem:read"], description="Local codebase search (grep) for functions/classes/symbols", params=[S("query", "str", True, description="Regex or text query", max_length=500), S("max_results", "int", False, 20, "Max matches (1-200)", minimum=1, maximum=200)], permission=PermissionLevel.READ_ONLY, execute_fn=_code_search, timeout=10, tags=["code","search"], error_strategy="abort"),
        ToolSpec(name="git.status", idempotent=True, capabilities=["filesystem:read", "shell:execute"], description="Get git status --short", params=[], permission=PermissionLevel.READ_ONLY, execute_fn=lambda: _git_status(), timeout=10, tags=["git","code"]),
        ToolSpec(name="git.diff", idempotent=True, capabilities=["filesystem:read", "shell:execute"], description="Get git diff (stat or full, capped)", params=[S("stat_only", "bool", False, True)], permission=PermissionLevel.READ_ONLY, execute_fn=_git_diff, timeout=10, tags=["git","code"]),
        ToolSpec(name="git.commit", capabilities=["filesystem:read", "filesystem:write", "shell:execute"], description="git add (secrets excluded) + commit", params=[S("message", "str", True, description="Commit message", max_length=2000), S("add_all", "bool", False, True)], permission=PermissionLevel.SENSITIVE, execute_fn=_git_commit, timeout=45, tags=["git","code"], error_strategy="abort", idempotent=False),
        ToolSpec(name="terminal.run", capabilities=["filesystem:read", "filesystem:write", "shell:execute"], description="Run an allowlisted dev command (git status/diff/log/add/commit, pytest, ruff check, npm test/run, python/node <project script file>); no shell, max 120s", params=[S("command", "str", True, max_length=4000), S("timeout", "int", False, 15, "Seconds (1-120)", minimum=1, maximum=_MAX_TERMINAL_TIMEOUT)], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_terminal_run, timeout=130, tags=["terminal","code"], error_strategy="abort", idempotent=False),
        ToolSpec(name="test.run", capabilities=["filesystem:read", "shell:execute"], description="Run pytest suite and return results", params=[S("path", "str", False, "tests/", max_length=1024), S("verbose", "bool", False, False)], permission=PermissionLevel.SAFE_ACTION, execute_fn=_test_run, timeout=65, tags=["test","code"], error_strategy="abort"),
        ToolSpec(name="python.exec", capabilities=["filesystem:read", "shell:execute"], description="Execute python code in the isolated sandbox", params=[S("code", "str", True, max_length=100_000), S("timeout", "int", False, 15, "Seconds (1-120)", minimum=1, maximum=_MAX_TERMINAL_TIMEOUT)], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_python_exec, timeout=20, tags=["python","code"], error_strategy="abort", idempotent=False),
        ToolSpec(name="project.explain", idempotent=True, capabilities=["filesystem:read"], description="Generate multi-level project explanation (Beginner/Intermediate/Architect)", params=[], permission=PermissionLevel.READ_ONLY, execute_fn=lambda: _project_explain(), timeout=30, tags=["code","intelligence"]),
    ]

    for spec in specs:
        registry.register(spec)
        count += 1
        logger.info(f"[CodingTools] Registered: {spec.name} [{spec.permission.name}]")

    return count

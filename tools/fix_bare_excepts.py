"""
fix_bare_excepts.py — one-shot migration to eliminate silent exception swallowing.

Transforms (AST-driven, idempotent, parse-checked per file):
  except:                       -> except Exception as _e:
  except X:                     -> except X as _e:        (when body swallows)
  except X: pass                -> except X as _e:
                                   logging.debug(...)
  except X: continue            -> except X as _e:
                                   logging.debug(...)
                                   continue
  except (A, B):   (multi-line) -> collapsed to one line + as-name + logging

Every rewritten handler logs at debug level (info when the original comment
marks the path as expected/optional/best-effort). `import logging` is added to
files that lack it. Files whose result fails to parse are left untouched.
"""
import ast
import logging
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {
    ".git", "__pycache__", "flexie_web", "browser_session", ".venv", "venv",
    ".pytest_cache", ".ruff_cache", ".github", "tests", "tools",
    "node_modules", "recovery", "temp_test_chroma",
}

INFO_HINTS = ("expected", "optional", "best-effort", "best effort", "tolerate")


def split_comment(tail):
    """Split 'except X: body  # comment' tail into (code, comment)."""
    q = None
    for idx, ch in enumerate(tail):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#":
            return tail[:idx].rstrip(), tail[idx:]
    return tail.rstrip(), ""


class Src:
    def __init__(self, text):
        self.lines = text.splitlines(keepends=True)

    def get(self, i):
        return self.lines[i].rstrip("\r\n") if 0 <= i < len(self.lines) else ""

    def indent_of(self, i):
        m = re.match(r"[ \t]*", self.get(i))
        return m.group(0) if m else ""

    def eol(self, i):
        return "\r\n" if i < len(self.lines) and self.lines[i].endswith("\r\n") else "\n"

    def set(self, i, text):
        self.lines[i] = text + self.eol(i)

    def insert_after(self, i, text):
        self.lines.insert(i + 1, text + self.eol(i))

    def splice_out(self, start, end):
        """Remove lines[start..end] inclusive."""
        del self.lines[start:end + 1]

    def text(self):
        return "".join(self.lines)

    def __len__(self):
        return len(self.lines)


def is_silent(node):
    """True when the handler body swallows the exception without logging."""
    for stmt in node.body:
        src_seg = ast.unparse(stmt)
        if "logging." in src_seg or "logger." in src_seg or "self.logger" in src_seg:
            return False
        if isinstance(stmt, ast.Raise):
            return False  # re-raise is not silent
    return True


def has_inline_body(node):
    """True when any body statement starts on the same line as 'except'."""
    return any(stmt.lineno == node.lineno for stmt in node.body)


def log_stmt(indent, level, relpath, line_no, name):
    ctx = relpath.replace("\\", "/")
    return (
        f'{indent}logging.{level}('
        f'"[{ctx}:{line_no}] Swallowed exception: %s: %s", '
        f'type({name}).__name__, {name})'
    )


def header_line(indent, node, raw):
    """Build the new except header, preserving any trailing comment."""
    _, comment = split_comment(raw.strip())
    type_src = ast.unparse(node.type) if node.type is not None else "Exception"
    name = node.name if node.name else "_e"
    head = f"{indent}except {type_src} as {name}:"
    if comment:
        head += "  " + comment
    return head, name


def process_handler(src, node, relpath):
    """Rewrite one silent except handler. Returns edits count or 0."""
    i = node.lineno - 1
    raw = src.get(i)
    indent = src.indent_of(i)
    low = raw.lower()
    level = "info" if any(h in low for h in INFO_HINTS) else "debug"

    head, name = header_line(indent, node, raw)
    body_indent = indent + "    "
    log_line = log_stmt(body_indent, level, relpath, i + 1, name)

    if has_inline_body(node):
        # One-liner: expand fully via unparse (drops inline comments in body —
        # acceptable for `except X: pass/continue`-style one-liners).
        if any(not isinstance(s, (ast.Pass, ast.Continue, ast.Break, ast.Expr))
               for s in node.body):
            # complex inline body — expand but keep unparsed statements
            pass
        type_end = (node.type.end_lineno if node.type is not None else i + 1)
        # splice out the original single line (and any type continuation lines)
        src.splice_out(i, max(i, type_end - 1))
        new_lines = [head, log_line]
        for stmt in node.body:
            if isinstance(stmt, ast.Pass):
                continue  # logging call makes body non-empty; pass redundant
            new_lines.append(body_indent + ast.unparse(stmt))
        # insert all new lines after position i-1 (i.e., at index i)
        for offset, line in enumerate(new_lines):
            src.lines.insert(i + offset, line + "\n")
        return 1

    # Multi-line body: header may still span multiple lines (tuple types).
    type_end = (node.type.end_lineno if node.type is not None else i + 1)
    if type_end - 1 > i:
        # collapse multi-line except clause header to one line
        src.splice_out(i, type_end - 1)
        src.lines.insert(i, head + "\n")
    else:
        src.set(i, head)

    # Insert logging as first statement of the body.
    first_body = min(s.lineno for s in node.body) - 1
    # after splicing, body lines shifted by (old header span - 1)
    shift = (type_end - 1) - i  # lines removed beyond the first
    first_body -= shift
    src.insert_after(i, log_line)
    return 1


def collect_handlers(tree):
    return [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]


def ensure_logging_import(src):
    text = src.text()
    if re.search(r"^import logging\b", text, re.M) or re.search(r"^from logging import\b", text, re.M):
        return
    last_import = -1
    for i in range(min(len(src), 200)):
        s = src.get(i).strip()
        if re.match(r"^(import|from)\s", s):
            last_import = i
        elif last_import >= 0 and s and not s.startswith(("#", ")")):
            break
    if last_import < 0:
        src.lines.insert(0, "import logging\n")
    else:
        src.insert_after(last_import, "import logging")


def process_file(path):
    relpath = os.path.relpath(path, ROOT)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        original = f.read()

    try:
        tree = ast.parse(original)
    except SyntaxError:
        return 0

    # Process handlers bottom-up so line indices stay valid as we splice.
    handlers = sorted(
        collect_handlers(tree), key=lambda n: n.lineno, reverse=True
    )

    src = Src(original)
    edits = 0
    for node in handlers:
        if not is_silent(node):
            continue
        try:
            edits += process_handler(src, node, relpath)
        except Exception as e:
            logging.warning("fix_bare_excepts: %s line %s: %s", relpath, node.lineno, e)
            return 0  # abandon this file safely (unchanged — we write only at end)

    if not edits:
        return 0

    ensure_logging_import(src)

    new_text = src.text()
    try:
        ast.parse(new_text)
    except SyntaxError as e:
        logging.error("fix_bare_excepts: %s invalid result (%s); skipped", relpath, e)
        return 0

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return edits


def main():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(os.path.join(dirpath, fn))

    total_files = 0
    for path in files:
        try:
            n = process_file(path)
        except Exception as e:
            logging.error("fix_bare_excepts: failed on %s: %s", path, e)
            n = 0
        if n:
            total_files += 1
            print(f"  fixed {n:3d} site(s): {os.path.relpath(path, ROOT)}")

    print(f"\n{total_files} file(s) modified")


if __name__ == "__main__":
    main()

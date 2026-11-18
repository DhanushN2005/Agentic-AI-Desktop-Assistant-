"""Code Generation Engine for Build Jobs.

Features:
- File-by-file generation with per-call max_tokens and per-job token budgeting.
- Strict isolation from web-search snippets (use_rag=False).
- Code fence and prose stripping (outer wrapper only; inner fences preserved).
- Syntax validation before writing: ast.parse (Python), json.loads (JSON),
  tokenizer-aware bracket checks (JS/TS), tag balance (HTML), brace balance (CSS).
- Single-repair attempt on syntax failure; marks phase failed if repair fails.
- Path jail enforcement, secret neutralization, and .env.example auto-generation.
- Resource caps: max 60 files, max 300 KB per file.
"""
from __future__ import annotations

import ast
import io
import json
import logging
import math
import os
import re
import tokenize
from html.parser import HTMLParser
from typing import Any

from core.jobs.lessons import lessons_block
from core.jobs.models import BuildJob, JobPhase
from core.jobs.planner import ProjectFileSpec, ProjectSpec
from core.jobs.safe_paths import atomic_write, count_source_files, safe_join
from utils.config import Config

logger = logging.getLogger("flexie.jobs.generator")

MAX_FILES_PER_PROJECT: int = getattr(Config, "JOB_MAX_FILES", 60)
MAX_FILE_SIZE_BYTES: int = getattr(Config, "JOB_MAX_FILE_SIZE_KB", 300) * 1024
_MAX_SIBLING_CHARS_EACH = 12_000
_MAX_SIBLING_CHARS_TOTAL = 60_000

# Provider-prefixed secret shapes: (pattern, env var name). Order matters
# (anthropic before the generic sk- shape).
_SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"), "ANTHROPIC_API_KEY"),
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), "OPENAI_API_KEY"),
    (re.compile(r"gsk_[a-zA-Z0-9_\-]{20,}"), "GROQ_API_KEY"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "GOOGLE_API_KEY"),
    (re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"), "AWS_ACCESS_KEY_ID"),
    (re.compile(r"github_pat_[0-9a-zA-Z_]{30,}"), "GITHUB_TOKEN"),
    (re.compile(r"gh[pousr]_[0-9a-zA-Z]{36,}"), "GITHUB_TOKEN"),
    (re.compile(r"xox[abprs]-[0-9A-Za-z\-]{10,}"), "SLACK_TOKEN"),
    (re.compile(r"glpat-[0-9A-Za-z_\-]{20,}"), "GITLAB_TOKEN"),
    (re.compile(r"SG\.[0-9A-Za-z_\-]{16,}\.[0-9A-Za-z_\-]{16,}"), "SENDGRID_API_KEY"),
    (re.compile(r"(?:sk|rk)_live_[0-9a-zA-Z]{20,}"), "STRIPE_SECRET_KEY"),
    (re.compile(r"hf_[0-9a-zA-Z]{30,}"), "HUGGINGFACE_TOKEN"),
]
_GENERIC_ASSIGN = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:api[_-]?key|secret|token|passwd|password|pwd|access[_-]?key)[A-Za-z0-9_]*)"
    r"\s*[:=]\s*(?P<q>[\"'])(?P<val>[^\"'\n]{16,})(?P=q)",
    re.IGNORECASE,
)
_PLACEHOLDER_WORDS = re.compile(
    r"your|example|changeme|placeholder|xxxx|dummy|sample|<|>|\$\{|process\.env|getenv|env\(|redacted|test",
    re.IGNORECASE,
)


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in freq.values())


def _looks_secret(val: str) -> bool:
    if len(val) < 16 or re.search(r"\s", val) or _PLACEHOLDER_WORDS.search(val):
        return False
    if not (re.search(r"[A-Za-z]", val) and re.search(r"\d", val)):
        return False
    return _entropy(val) >= 3.0


# ----------------------------------------------------------------- validation
_JS_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
_JS_KEYWORDS_BEFORE_REGEX = {
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
    "case", "do", "else", "yield", "await",
}


def _check_js_brackets(src: str, jsx: bool = False) -> str | None:
    """Bracket balance that ignores strings, template literals, comments and regexes."""
    pairs = {")": "(", "}": "{", "]": "["}
    stack: list[tuple[str, bool]] = []  # (char, is_template_expression)
    n = len(src)
    i = 0
    tmpl = False
    prev_sig = ""
    prev_word = ""
    while i < n:
        c = src[i]
        if tmpl:
            if c == "\\":
                i += 2
            elif c == "`":
                tmpl = False
                prev_sig = "`"
                i += 1
            elif c == "$" and src[i + 1:i + 2] == "{":
                stack.append(("{", True))
                tmpl = False
                prev_sig = "{"
                i += 2
            else:
                i += 1
            continue
        if c in " \t\r\n":
            i += 1
            continue
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if two == "/*":
            j = src.find("*/", i + 2)
            if j < 0:
                return "Unterminated block comment"
            i = j + 2
            continue
        if c in "\"'":
            if c == "'" and i > 0 and src[i - 1].isalnum():
                i += 1  # apostrophe in text (e.g. JSX "Don't"); JS has no string prefixes
                continue
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            prev_sig = '"'
            prev_word = ""
            continue
        if c == "`":
            tmpl = True
            i += 1
            continue
        if c == "/":
            regex_ok = prev_sig == "" or prev_sig in _JS_REGEX_PREV or prev_word in _JS_KEYWORDS_BEFORE_REGEX
            if jsx and prev_sig == "<":
                regex_ok = False
            if regex_ok:
                j = i + 1
                in_class = False
                found = -1
                while j < n:
                    ch = src[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "\n":
                        break
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        found = j
                        break
                    j += 1
                if found > 0:
                    i = found + 1
                    while i < n and src[i].isalpha():
                        i += 1
                    prev_sig = "a"
                    prev_word = ""
                    continue
            prev_sig = "/"
            prev_word = ""
            i += 1
            continue
        if c in "({[":
            stack.append((c, False))
            prev_sig = c
            prev_word = ""
            i += 1
            continue
        if c in ")}]":
            if c == "}" and stack and stack[-1] == ("{", True):
                stack.pop()
                tmpl = True
                i += 1
                continue
            if not stack or stack[-1][0] != pairs[c]:
                return f"Unbalanced bracket/brace: {c}"
            stack.pop()
            prev_sig = c
            prev_word = ""
            i += 1
            continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            prev_word = src[i:j]
            prev_sig = src[j - 1]
            i = j
            continue
        prev_sig = c
        prev_word = ""
        i += 1
    if tmpl:
        return "Unterminated template literal"
    if stack:
        return f"Unclosed open brackets/braces remaining: {''.join(c for c, _ in stack)}"
    return None


_HTML_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
}
_HTML_STRICT = {
    "html", "body", "div", "span", "section", "main", "nav", "header", "footer", "form",
    "table", "ul", "ol", "button", "script", "style", "a", "article", "aside", "select",
    "textarea", "label", "h1", "h2", "h3", "h4", "h5", "h6",
}


class _TagBalance(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.error: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag not in _HTML_VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        if tag in _HTML_VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                top = self.stack.pop()
                if top in _HTML_STRICT and self.error is None:
                    self.error = f"Unclosed <{top}> before </{tag}>"
            if self.stack:
                self.stack.pop()
        elif tag in _HTML_STRICT and self.error is None:
            self.error = f"Unexpected closing tag </{tag}>"


def _check_html(content: str) -> str | None:
    if "<" not in content or ">" not in content:
        return "HTML file lacks valid HTML tags."
    p = _TagBalance()
    try:
        p.feed(content)
        p.close()
    except Exception as e:  # HTMLParser is lenient; treat crashes as a soft pass
        logger.debug("HTML parse issue: %s", e)
        return None
    if p.error:
        return p.error
    left = [t for t in p.stack if t in _HTML_STRICT]
    if left:
        return f"Unclosed tags at end of file (truncated?): {', '.join('<' + t + '>' for t in left[:5])}"
    return None


def _check_css(content: str) -> str | None:
    text = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    if "/*" in text:
        return "Unterminated CSS comment"
    text = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '""', text)
    depth = 0
    paren = 0
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "Unbalanced closing brace in CSS"
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
            if paren < 0:
                return "Unbalanced closing parenthesis in CSS"
    if depth:
        return f"Unclosed CSS braces remaining: {depth}"
    if paren:
        return "Unclosed parenthesis in CSS"
    return None


def validate_syntax(filename: str, content: str) -> tuple[bool, str | None]:
    """Validate source code syntax before writing to disk."""
    if not content or not content.strip():
        return False, "Generated file content is completely empty."

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".py":
        try:
            ast.parse(content)
            return True, None
        except (SyntaxError, ValueError) as e:
            return False, f"Python SyntaxError on line {getattr(e, 'lineno', '?')}: {getattr(e, 'msg', e)}"

    elif ext == ".json":
        try:
            json.loads(content)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"JSONDecodeError on line {e.lineno}: {e.msg}"

    elif ext in (".html", ".htm"):
        err = _check_html(content)
        return (False, err) if err else (True, None)

    elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        err = _check_js_brackets(content, jsx=ext in (".jsx", ".tsx"))
        return (False, err) if err else (True, None)

    elif ext == ".css":
        err = _check_css(content)
        return (False, err) if err else (True, None)

    return True, None


# ------------------------------------------------------------------ fences
_FENCE_LINE = re.compile(r"^\s*```([A-Za-z0-9_\-+.#]*)\s*$")
_MARKDOWN_EXTS = {".md", ".markdown", ".txt", ".rst"}


def _unwrap_outer_fence(lines: list[str]) -> list[str] | None:
    """Return the lines inside the outermost fence, or None if there is no fence."""
    start = next((i for i, ln in enumerate(lines) if _FENCE_LINE.match(ln)), None)
    if start is None:
        return None
    depth = 0
    end = None
    for j in range(start + 1, len(lines)):
        m = _FENCE_LINE.match(lines[j])
        if not m:
            continue
        if m.group(1):
            depth += 1  # tagged fence: opens a nested block
        elif depth > 0:
            depth -= 1
        else:
            end = j
            break
    if end is None:
        bare = [j for j in range(start + 1, len(lines)) if _FENCE_LINE.match(lines[j]) and not _FENCE_LINE.match(lines[j]).group(1)]
        end = bare[-1] if bare else len(lines)
    return lines[start + 1:end]


def strip_fences_and_prose(filename: str, raw: str) -> str:
    """Extract source code, stripping only an outer markdown wrapper and stray prose.

    Inner fences are preserved. Markdown/text targets are only unwrapped when the
    whole reply is a single ```markdown block.
    """
    text = (raw or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    lines = text.splitlines()

    if ext in _MARKDOWN_EXTS:
        if lines:
            m = _FENCE_LINE.match(lines[0])
            if m and m.group(1).lower() in ("markdown", "md") and _FENCE_LINE.match(lines[-1]) and len(lines) > 1:
                return "\n".join(lines[1:-1]).strip()
        return text

    inner = _unwrap_outer_fence(lines)
    if inner is not None:
        code = "\n".join(inner).strip()
    else:
        first_code_idx = 0
        for i, line in enumerate(lines):
            l_strip = line.strip()
            if re.match(r"^(here is|here's|below is|sure|based on|i have|this file|note that)\b", l_strip, re.IGNORECASE):
                continue
            first_code_idx = i
            break
        code = "\n".join(lines[first_code_idx:]).strip()

    code = re.sub(r"(?i)based on my (web )?search.*?\n", "", code).strip()
    return code


# ------------------------------------------------------------------ secrets
def _env_name_from_var(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)).strip("_").upper()
    return n or "SECRET_VALUE"


def _find_secrets(content: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pattern, env_var in _SECRET_PATTERNS:
        for m in pattern.finditer(content):
            if m.group(0) not in seen:
                seen.add(m.group(0))
                found.append((m.group(0), env_var))
    for m in _GENERIC_ASSIGN.finditer(content):
        val = m.group("val")
        if val not in seen and _looks_secret(val):
            seen.add(val)
            found.append((val, _env_name_from_var(m.group("name"))))
    pk = re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", content, re.DOTALL)
    if pk and pk.group(0) not in seen:
        found.append((pk.group(0), "PRIVATE_KEY"))
    # Longest first so a secret that contains another is replaced whole.
    found.sort(key=lambda t: -len(t[0]))
    return found


def _py_replace(content: str, secrets: list[tuple[str, str]]) -> str:
    """Syntax-safe replacement for Python source using the tokenizer."""
    lookup = dict(secrets)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(content).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        toks = None
    if toks is None:
        out = content
        for s, env in secrets:
            out = out.replace(s, f"REDACTED_{env}")
        return out
    line_starts = [0]
    for ln in content.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(ln))
    fmid = getattr(tokenize, "FSTRING_MIDDLE", -1)
    edits: list[tuple[int, int, str]] = []
    for t in toks:
        if t.type not in (tokenize.STRING, tokenize.COMMENT, fmid):
            continue
        if not any(s in t.string for s in lookup):
            continue
        (sr, sc), (er, ec) = t.start, t.end
        if sr - 1 >= len(line_starts) or er - 1 >= len(line_starts):
            continue
        a, b = line_starts[sr - 1] + sc, line_starts[er - 1] + ec
        new = t.string
        if t.type == tokenize.STRING:
            m = re.match(r"^([A-Za-z]*)('''|\"\"\"|'|\")(.*)\2$", t.string, re.DOTALL)
            if m and m.group(3) in lookup and not (set(m.group(1).lower()) & {"f", "b"}):
                new = f'os.getenv("{lookup[m.group(3)]}", "")'
        if new == t.string:
            for s, env in secrets:
                new = new.replace(s, f"REDACTED_{env}")
        edits.append((a, b, new))
    out = content
    for a, b, new in sorted(edits, reverse=True):
        out = out[:a] + new + out[b:]
    return out


def _py_ensure_os_import(src: str) -> str:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name == "os" and not a.asname for a in node.names):
                return src
        idx = 0
        for i, node in enumerate(tree.body):
            is_doc = i == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and isinstance(node.value.value, str)
            is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
            if is_doc or is_future:
                idx = max(idx, node.end_lineno or 0)
        lines = src.splitlines(keepends=True)
        lines.insert(idx, "import os\n")
        return "".join(lines)
    return src if re.search(r"^\s*import\s+os\b", src, re.MULTILINE) else "import os\n" + src


def neutralize_secrets(content: str, workspace_path: str, filename: str) -> tuple[str, list[str]]:
    """Scan and replace hardcoded secrets with environment variable references.

    Replacement is syntax-safe: a secret that *is* a whole string literal becomes an
    env lookup; one embedded in a larger string/comment becomes a ``REDACTED_*`` text
    token. Also ensures .env.example lists the neutralized variables.
    """
    if not isinstance(content, str) or not content:
        return content, []
    secrets = _find_secrets(content)
    if not secrets:
        return content, []

    is_python = filename.endswith(".py")
    is_js = filename.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
    modified = content
    if is_python:
        modified = _py_replace(modified, secrets)
        if "os.getenv(" in modified and "os.getenv(" not in content:
            modified = _py_ensure_os_import(modified)
    elif is_js:
        for s, env in secrets:
            modified = re.sub(r"([\"'`])" + re.escape(s) + r"\1", f"process.env.{env}", modified)
            modified = modified.replace(s, f"REDACTED_{env}")
    else:
        for s, env in secrets:
            modified = modified.replace(s, f"${{{env}}}")

    detected_keys: list[str] = []
    for _, env in secrets:
        if env not in detected_keys:
            detected_keys.append(env)

    env_example_path = os.path.join(workspace_path, ".env.example")
    existing_lines: list[str] = []
    if os.path.exists(env_example_path):
        try:
            with open(env_example_path, encoding="utf-8") as f:
                existing_lines = [line.strip() for line in f.readlines() if line.strip()]
        except OSError as e:
            logger.debug("Could not read %s: %s", env_example_path, e)
    for k in detected_keys:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
            continue
        if not any(el.startswith(f"{k}=") for el in existing_lines):
            existing_lines.append(f"{k}=your_{k.lower()}_here")
    try:
        with open(env_example_path, "w", encoding="utf-8") as f:
            f.write("\n".join(existing_lines) + "\n")
        logger.info("Updated .env.example with neutralized keys: %s", detected_keys)
    except Exception as e:
        logger.warning("Could not write .env.example: %s", e)

    return modified, detected_keys


# --------------------------------------------------------------- generator
class CodeGenerator:
    """Manages file-by-file code generation with token budgets and safety validation."""

    def __init__(
        self,
        token_budget: int | None = None,
        max_tokens_per_call: int | None = None,
    ):
        self.token_budget = token_budget or getattr(Config, "JOB_TOKEN_BUDGET", 200000)
        # 8192 keeps a full 300-line file without truncation; Config.CODE_MAX_TOKENS overrides
        self.max_tokens_per_call = max_tokens_per_call or getattr(Config, "CODE_MAX_TOKENS", 8192)

    def _enhance_intent(self, brain: Any, file_spec: ProjectFileSpec, spec: ProjectSpec, job: BuildJob) -> str:
        """Expand the short file purpose into a detailed implementation plan before coding."""
        ext = os.path.splitext(file_spec.name)[1].lower()
        if ext not in (".js", ".jsx", ".ts", ".tsx", ".py", ".html", ".htm"):
            return file_spec.purpose

        prompt = f"""Project: {spec.title}
Summary: {spec.summary}
File: {file_spec.name}
Base Purpose: {file_spec.purpose}

Write a detailed, step-by-step implementation plan for THIS specific file.
What features must be coded? What edge cases handled?
If this is a frontend file, how should the UI/UX look and feel?
If this is a backend file, what is the exact data flow and schema?
DO NOT write code. Output only the plain text plan (max 200 words)."""
        try:
            plan = brain.ask(
                prompt,
                system_override="You are a senior technical lead planning file implementations.",
                use_rag=False,
                max_tokens=500,
            )
            job.tokens_used += len(prompt + (plan or "")) // 4
            return plan.strip() if isinstance(plan, str) and plan else file_spec.purpose
        except Exception as e:
            logger.warning("Intent enhancement failed for %s: %s", file_spec.name, e)
            return file_spec.purpose

    @staticmethod
    def _read_siblings(job: BuildJob, sibling_files: list[str]) -> str:
        """Read already-written sibling files through the path jail, size-bounded."""
        out = ""
        for s_file in sibling_files:
            if len(out) >= _MAX_SIBLING_CHARS_TOTAL:
                break
            base = os.path.basename(str(s_file)).lower()
            if base.startswith(".env") or base.endswith((".pem", ".key")):
                continue
            try:
                s_path = safe_join(job.workspace_path, s_file)
            except ValueError as e:
                logger.warning("Job %s: sibling path %r rejected: %s", job.id, s_file, e)
                continue
            if not os.path.isfile(s_path):
                continue
            try:
                with open(s_path, encoding="utf-8") as f:
                    content = f.read(_MAX_SIBLING_CHARS_EACH + 1)
            except (OSError, UnicodeDecodeError) as _e:
                logger.debug("Could not read sibling %s: %s", s_path, _e)
                continue
            if content.strip():
                if len(content) > _MAX_SIBLING_CHARS_EACH:
                    content = content[:_MAX_SIBLING_CHARS_EACH] + "\n... [truncated]"
                out += f"\n--- {s_file} ---\n{content}\n"
        return out

    def generate_single_file(
        self,
        job: BuildJob,
        file_spec: ProjectFileSpec,
        brain: Any,
        spec: ProjectSpec,
    ) -> tuple[bool, str]:
        """Generate, validate, and write a single source file safely.

        Returns (success: bool, error_message: str).
        """
        # 1. Check token budget
        if job.tokens_used >= self.token_budget:
            msg = f"Token budget exceeded ({job.tokens_used}/{self.token_budget} tokens)."
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # 2. Check total file count cap (source files only; deps/VCS dirs pruned)
        n_files = count_source_files(job.workspace_path)
        if n_files >= MAX_FILES_PER_PROJECT:
            msg = f"File count limit reached ({n_files}/{MAX_FILES_PER_PROJECT})."
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # 3. Path jail & safety checks
        try:
            dest_path = safe_join(job.workspace_path, file_spec.name)
        except Exception as e:
            msg = f"File path rejected by security jail: {e}"
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # Skip regenerating files that already exist from a real template (not stubs)
        if os.path.exists(dest_path) and file_spec.name != "README.md":
            try:
                with open(dest_path, encoding="utf-8") as _ef:
                    _existing = _ef.read()
                _real_lines = [
                    line
                    for line in _existing.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                if len(_real_lines) >= 2:
                    logger.info("File %s already has real content; keeping it.", file_spec.name)
                    return True, ""
            except (OSError, UnicodeDecodeError) as e:
                logger.debug("Could not read %s: %s", dest_path, e)

        enhanced_purpose = self._enhance_intent(brain, file_spec, spec, job)

        sibling_files = [f.name for f in spec.files if f.name != file_spec.name]
        ext = os.path.splitext(file_spec.name)[1].lower()

        existing_files_content = self._read_siblings(job, sibling_files)
        existing_files_block = ""
        if existing_files_content:
            existing_files_block = f"\nEXISTING FILE CONTENTS (Use these to ensure IDs, classes, and function names match exactly):\n{existing_files_content}\n"

        # Per-project, sanitized, bounded notes (data, not instructions)
        try:
            lessons_text = lessons_block(job.id)
        except Exception as _e:
            logger.debug("lessons unavailable: %s", _e)
            lessons_text = ""

        file_type_rules = ""
        if ext in (".html", ".htm"):
            file_type_rules = (
                "HTML RULES:\n"
                "- Write a COMPLETE, fully functional HTML page. Do NOT write a loading screen or placeholder.\n"
                "- Include ALL UI elements described in the project summary — fully rendered, not stubs.\n"
                "- Use semantic HTML5 elements. Include proper <head> with charset, viewport, title.\n"
                "- MUST import a modern font like Google Fonts (Inter, Roboto) and FontAwesome for icons.\n"
                "- Link to all CSS and JS sibling files correctly (relative paths).\n"
                "- The page must be usable immediately when opened in a browser with no additional steps.\n"
            )
        elif ext in (".js", ".ts"):
            file_type_rules = (
                "JAVASCRIPT RULES:\n"
                "- Implement an END-TO-END working application. No TODO comments, no stubs.\n"
                "- All functions must have a complete, working body.\n"
                "- Use vanilla JS (no CDN imports) unless the spec explicitly lists a library as a dependency.\n"
                "- Handle edge cases: empty state, invalid inputs, boundary conditions.\n"
                "- Manage all DOM updates efficiently and handle all user interactions (clicks, keyboard).\n"
                "- If it's a calendar: implement full month/year navigation, day rendering, holiday/event display.\n"
            )
        elif ext in (".jsx", ".tsx"):
            file_type_rules = (
                "REACT RULES:\n"
                "- Implement a fully functional, production-ready React component or app.\n"
                "- Use Hooks (useState, useEffect, useMemo) correctly. No stub components.\n"
                "- Implement all required state transitions, error handling, and end-to-end logic.\n"
                "- If it needs styling, use inline styles or import CSS properly.\n"
                "- Must be fully interactive and handle user events flawlessly.\n"
            )
        elif ext == ".css":
            file_type_rules = (
                "CSS RULES:\n"
                "- Write COMPLETE styles — every element referenced in the HTML must be styled beautifully.\n"
                "- Implement a premium, modern visual design (e.g. glassmorphism, soft shadows, vibrant gradients, or sleek dark mode).\n"
                "- Include hover states, transitions, and micro-animations for interactivity.\n"
                "- Use CSS variables for the color palette.\n"
                "- Ensure responsive layout with media queries for mobile and tablet.\n"
            )
        elif ext == ".py":
            file_type_rules = (
                "PYTHON RULES:\n"
                "- Write production-quality Python. No stub functions, no pass-only implementations.\n"
                "- All routes/endpoints must have complete, working logic for an END-TO-END flow.\n"
                "- If the app requires data storage, automatically include SQLite schema creation and setup logic.\n"
                "- Handle errors with proper try/except and return meaningful HTTP status codes.\n"
                "- Include all imports at the top. Never use bare 'except:'.\n"
                "- If the program starts a server, read the port from the PORT environment variable.\n"
            )

        acceptance_block = ""
        if spec.acceptance_criteria:
            acceptance_block = "\nACCEPTANCE CRITERIA (your code MUST satisfy ALL of these):\n"
            for i, c in enumerate(spec.acceptance_criteria, 1):
                acceptance_block += f"  {i}. {c}\n"

        prompt = f"""You are a Principal Software Engineer implementing a real production project.

PROJECT: {spec.title}
STACK: {spec.stack}
SUMMARY: {spec.summary}
DEPENDENCIES: {', '.join(spec.dependencies) if spec.dependencies else 'none'}
OTHER FILES IN THIS PROJECT: {', '.join(sibling_files) if sibling_files else 'none'}
{acceptance_block}
FILE TO IMPLEMENT: {file_spec.name}
DETAILED IMPLEMENTATION PLAN: {enhanced_purpose}
{existing_files_block}
{lessons_text}

{file_type_rules}
CRITICAL RULES (VIOLATIONS = BUILD FAILURE):
1. Output ONLY the raw source code inside a single markdown code block. NOTHING else.
2. The code must be 100% complete and immediately runnable. NO placeholders, NO TODOs, NO '...' gaps, NO stub functions.
3. Do NOT write a loading screen, splash screen, or empty skeleton instead of the real UI.
4. Do NOT include explanations, comments about what to add later, or apologies.
5. Every function, class, and UI element described must be FULLY implemented.
6. The file must integrate correctly with the other files listed above.

Write the complete, production-ready source code for {file_spec.name} now:"""

        system_prompt = (
            "You are an expert software engineer who writes complete, production-ready code. "
            "You NEVER write stubs, skeletons, loading placeholders, or incomplete implementations. "
            "You ALWAYS implement every feature fully. "
            "You output ONLY valid source code in a markdown code block — no prose, no explanations."
        )

        raw_code = ""
        try:
            raw_code = brain.ask(
                prompt,
                system_override=system_prompt,
                use_rag=False,
                max_tokens=self.max_tokens_per_call,
            )
            if not isinstance(raw_code, str):
                raw_code = "" if raw_code is None else str(raw_code)
            job.tokens_used += len(prompt + raw_code) // 4
        except Exception as e:
            msg = f"LLM code generation failed for {file_spec.name}: {e}"
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        clean_code = strip_fences_and_prose(file_spec.name, raw_code)
        clean_code, _ = neutralize_secrets(clean_code, job.workspace_path, file_spec.name)

        valid, syntax_err = validate_syntax(file_spec.name, clean_code)
        if not valid:
            logger.warning("File %s syntax check failed: %s. Attempting repair pass...", file_spec.name, syntax_err)
            repair_prompt = f"""You are a code repair engine. The file {file_spec.name} has a syntax error that must be fixed.

PROJECT: {spec.title} ({spec.stack})
FILE PURPOSE: {file_spec.purpose}

SYNTAX ERROR:
{syntax_err}

BROKEN CODE:
```
{clean_code[:12000]}
```

Return ONLY the complete, corrected source code inside a single code fence. Fix ALL syntax errors. Do not truncate or add stubs."""
            try:
                repair_raw = brain.ask(
                    repair_prompt,
                    system_override="You are an automated code repair assistant. Output ONLY complete, corrected, working source code in a code fence.",
                    use_rag=False,
                    max_tokens=self.max_tokens_per_call,
                )
                if not isinstance(repair_raw, str):
                    repair_raw = "" if repair_raw is None else str(repair_raw)
                job.tokens_used += len(repair_prompt + repair_raw) // 4
                repaired_code = strip_fences_and_prose(file_spec.name, repair_raw)
                repaired_code, _ = neutralize_secrets(repaired_code, job.workspace_path, file_spec.name)

                valid, syntax_err = validate_syntax(file_spec.name, repaired_code)
                if valid:
                    clean_code = repaired_code
                else:
                    msg = f"Syntax error persisted after repair for {file_spec.name}: {syntax_err}"
                    logger.error("Job %s: %s", job.id, msg)
                    return False, msg
            except Exception as re_err:
                msg = f"Repair pass failed for {file_spec.name}: {re_err}"
                logger.error("Job %s: %s", job.id, msg)
                return False, msg

        code_bytes = clean_code.encode("utf-8")
        if len(code_bytes) > MAX_FILE_SIZE_BYTES:
            msg = f"Generated file {file_spec.name} exceeds max size ({len(code_bytes)} bytes > {MAX_FILE_SIZE_BYTES} bytes)."
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        try:
            atomic_write(dest_path, clean_code)
            logger.info("Job %s: Successfully generated %s (%d bytes)", job.id, file_spec.name, len(code_bytes))
            return True, ""
        except Exception as e:
            msg = f"Failed writing file {file_spec.name}: {e}"
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

    def generate_all_files(
        self,
        job: BuildJob,
        brain: Any,
        phase: JobPhase | None = None,
    ) -> bool:
        """Iterate over all files declared in the ProjectSpec and write them."""
        spec_data = job.metadata.get("spec")
        if not spec_data:
            err = "Job has no ProjectSpec metadata to generate code from."
            logger.error(err)
            if phase:
                phase.error = err
            return False

        spec = ProjectSpec.from_dict(spec_data)
        generated_count = 0
        failed_files: list[str] = []
        capacity_failed: list[str] = []
        last_error: str = ""

        for file_spec in spec.files:
            if file_spec.name in ("PLAN.md", "ACCEPTANCE.md", "AGENTS.md"):
                continue

            success, err_msg = self.generate_single_file(job, file_spec, brain, spec)
            if success:
                generated_count += 1
            else:
                failed_files.append(file_spec.name)
                last_error = err_msg or last_error
                if (err_msg or "").startswith(("Token budget exceeded", "File count limit reached")):
                    capacity_failed.append(file_spec.name)
                logger.warning("Job %s: failed to generate %s — %s", job.id, file_spec.name, err_msg)

        if phase:
            if failed_files:
                phase.error = f"Failed to generate: {', '.join(failed_files)}"
            phase.output = (
                f"Generated {generated_count} source files successfully"
                + (f"; {len(failed_files)} failed." if failed_files else ".")
            )
        if failed_files:
            job.error = last_error
        if capacity_failed:
            msg = (
                f"{last_error} {len(capacity_failed)} file(s) were not generated "
                f"({', '.join(capacity_failed)}). Resume the job to continue with a fresh budget."
            )
            job.error = msg
            if phase:
                phase.error = msg
            return False
        total_targets = len([f for f in spec.files if f.name not in ("PLAN.md", "ACCEPTANCE.md", "AGENTS.md")])
        return not (total_targets > 0 and generated_count == 0)

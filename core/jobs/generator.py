"""Code Generation Engine for Build Jobs.

Features:
- File-by-file generation with per-call max_tokens and per-job token budgeting.
- Strict isolation from web-search snippets (use_rag=False).
- Code fence and prose stripping.
- Syntax validation before writing: ast.parse (Python), json.loads (JSON), tag/bracket checks (HTML/JS).
- Single-repair attempt on syntax failure; marks phase failed if repair fails.
- Path jail enforcement, secret neutralization, and .env.example auto-generation.
- Resource caps: max 60 files, max 300 KB per file.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from core.jobs.models import BuildJob, JobPhase
from core.jobs.planner import ProjectFileSpec, ProjectSpec
from utils.config import Config
from utils.path_jail import resolve_in_root

logger = logging.getLogger("flexie.jobs.generator")

MAX_FILES_PER_PROJECT = 60
MAX_FILE_SIZE_BYTES = 300 * 1024  # 300 KB

# Secret patterns to detect and neutralize
_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), "OPENAI_API_KEY"),
    (re.compile(r"gsk_[a-zA-Z0-9_\-]{20,}"), "GROQ_API_KEY"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "GOOGLE_API_KEY"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS_ACCESS_KEY_ID"),
    (re.compile(r"ghp_[0-9a-zA-Z]{36}"), "GITHUB_TOKEN"),
]


def validate_syntax(filename: str, content: str) -> Tuple[bool, Optional[str]]:
    """Validate source code syntax before writing to disk."""
    if not content or not content.strip():
        return False, "Generated file content is completely empty."

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".py":
        try:
            ast.parse(content)
            return True, None
        except SyntaxError as e:
            return False, f"Python SyntaxError on line {e.lineno}: {e.msg}"

    elif ext == ".json":
        try:
            json.loads(content)
            return True, None
        except json.JSONDecodeError as e:
            return False, f"JSONDecodeError on line {e.lineno}: {e.msg}"

    elif ext in (".html", ".htm"):
        # Basic HTML sanity: must contain tags if non-trivial
        if "<" not in content or ">" not in content:
            return False, "HTML file lacks valid HTML tags."
        return True, None

    elif ext in (".js", ".jsx", ".ts", ".tsx"):
        # Check matching curly braces, parens, brackets
        stack = []
        pairs = {")": "(", "}": "{", "]": "["}
        for ch in content:
            if ch in "({[":
                stack.append(ch)
            elif ch in ")}]":
                if not stack or stack[-1] != pairs[ch]:
                    return False, f"Unbalanced bracket/brace: {ch}"
                stack.pop()
        if stack:
            return False, f"Unclosed open brackets/braces remaining: {''.join(stack)}"
        return True, None

    # Text, md, css, configs: basic non-empty check
    return True, None


def strip_fences_and_prose(filename: str, raw: str) -> str:
    """Extract source code, stripping markdown fences and stray prose."""
    text = raw.strip()
    # Check for markdown code fences
    fence_pattern = re.compile(r"```(?:[a-zA-Z0-9_\-\+]*\n)?(.*?)```", re.DOTALL)
    m = fence_pattern.search(text)
    if m:
        code = m.group(1).strip()
    else:
        # Strip leading conversational sentences if present
        lines = text.splitlines()
        first_code_idx = 0
        for i, line in enumerate(lines):
            l_strip = line.strip()
            # If line looks like conversation
            if re.match(r"^(here is|here's|below is|sure|based on|i have|this file|note that)\b", l_strip, re.IGNORECASE):
                continue
            first_code_idx = i
            break
        code = "\n".join(lines[first_code_idx:]).strip()

    # Drop search attribution artifacts if any
    code = re.sub(r"(?i)based on my (web )?search.*?\n", "", code).strip()
    return code


def neutralize_secrets(content: str, workspace_path: str, filename: str) -> Tuple[str, List[str]]:
    """Scan and replace hardcoded secrets with environment variable references.

    Also ensures .env.example exists in the workspace.
    """
    modified = content
    detected_keys: List[str] = []
    is_python = filename.endswith(".py")
    is_js = filename.endswith((".js", ".jsx", ".ts", ".tsx"))

    for pattern, env_var in _SECRET_PATTERNS:
        matches = pattern.findall(modified)
        if matches:
            detected_keys.append(env_var)
            for secret in set(matches):
                if is_python:
                    replacement = f'os.getenv("{env_var}", "")'
                    # Replace quoted secret with env var
                    modified = modified.replace(f'"{secret}"', replacement).replace(f"'{secret}'", replacement)
                    modified = modified.replace(secret, replacement)
                elif is_js:
                    replacement = f'process.env.{env_var}'
                    modified = modified.replace(f'"{secret}"', replacement).replace(f"'{secret}'", replacement)
                    modified = modified.replace(secret, replacement)
                else:
                    modified = modified.replace(secret, f"${{{env_var}}}")

    if detected_keys:
        # Ensure os is imported in Python files if needed
        if is_python and "os.getenv" in modified and "import os" not in modified:
            modified = "import os\n" + modified

        # Maintain .env.example in workspace
        env_example_path = os.path.join(workspace_path, ".env.example")
        existing_lines = []
        if os.path.exists(env_example_path):
            try:
                with open(env_example_path, "r", encoding="utf-8") as f:
                    existing_lines = [l.strip() for l in f.readlines() if l.strip()]
            except Exception:
                pass

        for k in detected_keys:
            line = f"{k}=your_{k.lower()}_here"
            if not any(el.startswith(f"{k}=") for el in existing_lines):
                existing_lines.append(line)

        try:
            with open(env_example_path, "w", encoding="utf-8") as f:
                f.write("\n".join(existing_lines) + "\n")
            logger.info("Updated .env.example with neutralized keys: %s", detected_keys)
        except Exception as e:
            logger.warning("Could not write .env.example: %s", e)

    return modified, detected_keys


class CodeGenerator:
    """Manages file-by-file code generation with token budgets and safety validation."""

    def __init__(
        self,
        token_budget: Optional[int] = None,
        max_tokens_per_call: Optional[int] = None,
    ):
        self.token_budget = token_budget or getattr(Config, "JOB_TOKEN_BUDGET", 50000)
        self.max_tokens_per_call = max_tokens_per_call or getattr(Config, "CODE_MAX_TOKENS", 4096)

    def generate_single_file(
        self,
        job: BuildJob,
        file_spec: ProjectFileSpec,
        brain: Any,
        spec: ProjectSpec,
    ) -> Tuple[bool, str]:
        """Generate, validate, and write a single source file safely.

        Returns (success: bool, error_message: str).
        """
        # 1. Check token budget
        if job.tokens_used >= self.token_budget:
            msg = f"Token budget exceeded ({job.tokens_used}/{self.token_budget} tokens)."
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # 2. Check total file count cap
        current_files = []
        for root, _, files in os.walk(job.workspace_path):
            current_files.extend(files)
        if len(current_files) >= MAX_FILES_PER_PROJECT:
            msg = f"File count limit reached ({len(current_files)}/{MAX_FILES_PER_PROJECT})."
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # 3. Path jail & safety checks
        try:
            dest_path = resolve_in_root(file_spec.name, job.workspace_path)
        except Exception as e:
            msg = f"File path rejected by security jail: {e}"
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # Skip regenerating files that already exist from template
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0 and file_spec.name != "README.md":
            logger.info("File %s already exists from template; keeping it.", file_spec.name)
            return True, ""

        # 4. Prompt LLM (use_rag=False to prevent web search snippet pollution)
        prompt = f"""Project: {spec.title} ({spec.stack})
Summary: {spec.summary}
File to implement: {file_spec.name}
Purpose: {file_spec.purpose}
Dependencies: {', '.join(spec.dependencies)}

Write the complete, functional, production-ready source code for {file_spec.name}.
Output ONLY the raw code inside a markdown code block. Do NOT include conversational commentary, explanations, or web search summaries.
"""
        raw_code = ""
        try:
            raw_code = brain.ask(
                prompt,
                system_override="You are a Principal Software Engineer. Output ONLY valid, working source code without conversational text or search results.",
                use_rag=False,
                max_tokens=self.max_tokens_per_call,
            )
            # Estimate token usage (~1 token per 4 chars)
            est_tokens = len(prompt + (raw_code or "")) // 4
            job.tokens_used += est_tokens
        except Exception as e:
            msg = f"LLM code generation failed for {file_spec.name}: {e}"
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # 5. Clean, sanitize, and neutralize secrets
        clean_code = strip_fences_and_prose(file_spec.name, raw_code or "")
        clean_code, _ = neutralize_secrets(clean_code, job.workspace_path, file_spec.name)

        # 6. Syntax validation
        valid, syntax_err = validate_syntax(file_spec.name, clean_code)
        if not valid:
            logger.warning("File %s syntax check failed: %s. Attempting repair pass...", file_spec.name, syntax_err)
            repair_prompt = f"""The following code for {file_spec.name} has a syntax error:
{syntax_err}

Original Code:
{clean_code[:3000]}

Fix all syntax errors and return ONLY the corrected, valid source code inside a code fence.
"""
            try:
                repair_raw = brain.ask(
                    repair_prompt,
                    system_override="You are an automated code repair assistant. Output ONLY corrected code.",
                    use_rag=False,
                    max_tokens=self.max_tokens_per_call,
                )
                job.tokens_used += len(repair_prompt + (repair_raw or "")) // 4
                repaired_code = strip_fences_and_prose(file_spec.name, repair_raw or "")
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

        # 7. File size check (max 300 KB)
        code_bytes = clean_code.encode("utf-8")
        if len(code_bytes) > MAX_FILE_SIZE_BYTES:
            msg = f"Generated file {file_spec.name} exceeds max size ({len(code_bytes)} bytes > {MAX_FILE_SIZE_BYTES} bytes)."
            logger.error("Job %s: %s", job.id, msg)
            return False, msg

        # 8. Write to workspace
        try:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(clean_code)
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
        phase: Optional[JobPhase] = None,
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

        for file_spec in spec.files:
            # Skip manifest/documentation files already created by scaffolder
            if file_spec.name in ("PLAN.md", "ACCEPTANCE.md", "AGENTS.md"):
                continue

            success, err_msg = self.generate_single_file(job, file_spec, brain, spec)
            if not success:
                if phase:
                    phase.error = err_msg
                job.error = err_msg
                return False
            generated_count += 1

        if phase:
            phase.output = f"Generated {generated_count} source files successfully."
        return True

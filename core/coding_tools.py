"""
Coding Tools Registry — registers autonomous coding tools into ToolRegistry.

Wired by FlexieOrchestrator after ToolRegistry creation.
All tools return ActionResult and go through PermissionSystem + Verification.
"""
import os
import re
import subprocess
import logging
from typing import Optional

from core.tool_registry import ToolRegistry, ToolSpec, ToolSchema, PermissionLevel
from core.action_result import ActionResult


def register_coding_tools(registry: ToolRegistry, orch) -> int:
    """Register all coding-autonomy tools. Returns count registered."""
    logger = logging.getLogger("Flexie.CodingTools")
    count = 0

    # --- Helper fns closing over orch ---
    def _file_read(path: str, start_line: int = 1, end_line: Optional[int] = None) -> ActionResult:
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
            if not os.path.exists(abs_path):
                return ActionResult.fail(message=f"File not found: {path}", intent="file.read")
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if end_line is None:
                end_line = len(lines)
            content = "".join(lines[start_line - 1:end_line])
            return ActionResult.ok(message=f"Read {path} lines {start_line}-{end_line}", intent="file.read", data={"content": content, "path": abs_path})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="file.read")

    def _file_write(path: str, content: str, mkdir: bool = True) -> ActionResult:
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
            if mkdir:
                os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            # log to memory
            try:
                if hasattr(orch, 'memory_manager') and orch.memory_manager:
                    from core.memory_manager import MemoryCategory
                    orch.memory_manager.remember(f"write:{os.path.basename(path)}", f"Wrote {path} ({len(content)} chars)", MemoryCategory.TASKS, importance=0.5, tags=["code","write"])
            except: pass
            return ActionResult.ok(message=f"Wrote {path} ({len(content)} chars)", intent="file.write", data={"path": abs_path})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="file.write")

    def _file_patch(path: str, original: str, replacement: str, expected_count: int = 1) -> ActionResult:
        try:
            abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
            if not os.path.exists(abs_path):
                return ActionResult.fail(message=f"File not found: {path}", intent="file.patch")
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            count = content.count(original)
            if count == 0:
                return ActionResult.fail(message="Original snippet not found in file", intent="file.patch", data={"found": 0})
            if count != expected_count:
                return ActionResult.fail(message=f"Expected {expected_count} occurrence(s) but found {count} - ambiguous patch", intent="file.patch")
            new_content = content.replace(original, replacement)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return ActionResult.ok(message=f"Patched {path} ({count} replacement)", intent="file.patch", data={"path": abs_path})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="file.patch")

    def _code_search(query: str, max_results: int = 20) -> ActionResult:
        try:
            from engines.code_search import CodeSearchEngine
            engine = CodeSearchEngine(workspace_path=os.getcwd())
            res = engine.search(query, max_results=max_results)
            summary = "\n".join([f"{m.file}:{m.line_start} | {m.content[:120]}" for m in res.matches[:10]])
            return ActionResult.ok(message=f"Found {res.total_matches} matches for '{query}'", intent="code.search", data={"matches": [m.to_dict() for m in res.matches], "summary": summary})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="code.search")

    def _git_status() -> ActionResult:
        try:
            out = subprocess.check_output(["git", "status", "--short"], text=True, timeout=10)
            if not out.strip():
                return ActionResult.ok(message="Git repo clean", intent="git.status", data={"output": out})
            return ActionResult.ok(message="Git status retrieved", intent="git.status", data={"output": out})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="git.status")

    def _git_diff(stat_only: bool = True) -> ActionResult:
        try:
            cmd = ["git", "diff", "--stat"] if stat_only else ["git", "diff"]
            out = subprocess.check_output(cmd, text=True, timeout=10)
            return ActionResult.ok(message="Git diff retrieved", intent="git.diff", data={"output": out or "(no diff)"})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="git.diff")

    def _git_commit(message: str, add_all: bool = True) -> ActionResult:
        try:
            if add_all:
                subprocess.check_call(["git", "add", "-A"], timeout=10)
            subprocess.check_call(["git", "commit", "-m", message], timeout=10)
            return ActionResult.ok(message=f"Committed: {message}", intent="git.commit")
        except subprocess.CalledProcessError as e:
            return ActionResult.fail(message=f"Git commit failed: {e}", intent="git.commit")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="git.commit")

    def _terminal_run(command: str, timeout: int = 15) -> ActionResult:
        try:
            from core.safety import SafetyGuard
            if not SafetyGuard().validate(command):
                return ActionResult.fail(message="Blocked by SafetyGuard", intent="terminal.run")
        except: pass
        try:
            proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            out = out.strip()[:4000]
            if proc.returncode == 0:
                return ActionResult.ok(message=f"Command succeeded", intent="terminal.run", data={"output": out, "returncode": 0})
            return ActionResult.fail(message=f"Command failed (exit {proc.returncode})", intent="terminal.run", data={"output": out, "returncode": proc.returncode})
        except subprocess.TimeoutExpired:
            return ActionResult.fail(message=f"Timeout after {timeout}s", intent="terminal.run")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="terminal.run")

    def _test_run(path: str = "tests/", verbose: bool = False) -> ActionResult:
        try:
            cmd = ["python", "-m", "pytest", path, "-q"] if not verbose else ["python", "-m", "pytest", path, "-v"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            out = out.strip()[:5000]
            if proc.returncode == 0:
                return ActionResult.ok(message="Tests passed", intent="test.run", data={"output": out})
            return ActionResult.fail(message="Tests failed", intent="test.run", data={"output": out, "returncode": proc.returncode})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="test.run")

    def _python_exec(code: str, timeout: int = 15, use_sandbox: bool = True) -> ActionResult:
        try:
            if use_sandbox:
                from sandbox.executor import SandboxExecutor
                # allow_host_fallback=True so it works without Docker, but still logged
                ex = SandboxExecutor(timeout=timeout, allow_host_fallback=True)
                out = ex.run_python_code(code)
                if "Execution Failure" in out or "Execution Error" in out or "refused" in out.lower():
                    return ActionResult.fail(message=out[:2000], intent="python.exec", data={"output": out})
                return ActionResult.ok(message="Python exec succeeded", intent="python.exec", data={"output": out[:4000]})
            else:
                proc = subprocess.run(["python", "-c", code], capture_output=True, text=True, timeout=timeout)
                out = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode == 0:
                    return ActionResult.ok(message="Python exec succeeded", intent="python.exec", data={"output": out[:4000]})
                return ActionResult.fail(message=out[:2000], intent="python.exec")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="python.exec")

    def _project_explain() -> ActionResult:
        try:
            if hasattr(orch, 'dev'):
                msg = orch.dev.explain_project()
                return ActionResult.ok(message=msg, intent="project.explain", data={"output": msg})
            return ActionResult.fail(message="DeveloperEngine not available", intent="project.explain")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="project.explain")

    # --- Register specs ---
    specs = [
        ToolSpec(name="file.read", description="Read a file with optional line range (autonomous coding)", params=[ToolSchema("path", "str", True, description="Relative or absolute file path"), ToolSchema("start_line", "int", False, 1, "Start line"), ToolSchema("end_line", "int", False, None, "End line")], permission=PermissionLevel.READ_ONLY, execute_fn=_file_read, timeout=5, tags=["file","code"], error_strategy="abort"),
        ToolSpec(name="file.write", description="Write/create a file (creates dirs). Used for code generation.", params=[ToolSchema("path", "str", True, description="Target file path"), ToolSchema("content", "str", True, description="Full file content"), ToolSchema("mkdir", "bool", False, True, "Create parent dirs")], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_file_write, timeout=10, tags=["file","code"], error_strategy="retry"),
        ToolSpec(name="file.patch", description="Surgical patch: replace exact original snippet with replacement in file", params=[ToolSchema("path", "str", True), ToolSchema("original", "str", True, description="Exact snippet to replace"), ToolSchema("replacement", "str", True), ToolSchema("expected_count", "int", False, 1)], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_file_patch, timeout=8, tags=["file","code"], error_strategy="abort"),
        ToolSpec(name="code.search", description="Local codebase search (grep) for functions/classes/symbols", params=[ToolSchema("query", "str", True, description="Regex or text query"), ToolSchema("max_results", "int", False, 20)], permission=PermissionLevel.READ_ONLY, execute_fn=_code_search, timeout=10, tags=["code","search"], error_strategy="abort"),
        ToolSpec(name="git.status", description="Get git status --short", params=[], permission=PermissionLevel.READ_ONLY, execute_fn=lambda: _git_status(), timeout=10, tags=["git","code"]),
        ToolSpec(name="git.diff", description="Get git diff (stat or full)", params=[ToolSchema("stat_only", "bool", False, True)], permission=PermissionLevel.READ_ONLY, execute_fn=_git_diff, timeout=10, tags=["git","code"]),
        ToolSpec(name="git.commit", description="git add -A + commit", params=[ToolSchema("message", "str", True, description="Commit message"), ToolSchema("add_all", "bool", False, True)], permission=PermissionLevel.SENSITIVE, execute_fn=_git_commit, timeout=15, tags=["git","code"], error_strategy="abort"),
        ToolSpec(name="terminal.run", description="Run a shell command (safety-guarded, 15s timeout)", params=[ToolSchema("command", "str", True), ToolSchema("timeout", "int", False, 15)], permission=PermissionLevel.USER_CONFIRMATION, execute_fn=_terminal_run, timeout=20, tags=["terminal","code"], error_strategy="retry"),
        ToolSpec(name="test.run", description="Run pytest suite and return results", params=[ToolSchema("path", "str", False, "tests/"), ToolSchema("verbose", "bool", False, False)], permission=PermissionLevel.READ_ONLY, execute_fn=_test_run, timeout=65, tags=["test","code"], error_strategy="abort"),
        ToolSpec(name="python.exec", description="Execute python code in sandbox (Docker if available, else host subprocess)", params=[ToolSchema("code", "str", True), ToolSchema("timeout", "int", False, 15), ToolSchema("use_sandbox", "bool", False, True)], permission=PermissionLevel.SAFE_ACTION, execute_fn=_python_exec, timeout=20, tags=["python","code"], error_strategy="retry"),
        ToolSpec(name="project.explain", description="Generate multi-level project explanation (Beginner/Intermediate/Architect)", params=[], permission=PermissionLevel.READ_ONLY, execute_fn=lambda: _project_explain(), timeout=30, tags=["code","intelligence"]),
    ]

    for spec in specs:
        registry.register(spec)
        count += 1
        logger.info(f"[CodingTools] Registered: {spec.name} [{spec.permission.name}]")

    return count

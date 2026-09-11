import logging
import os
from typing import Dict, Any
from agents.base import BaseAgent
from engines.developer import DeveloperEngine

class CodingAgent(BaseAgent):
    """Coding agent handling developer scripts execution, compilation, and sandboxing checks."""
    def __init__(self, dev_engine: DeveloperEngine = None):
        super().__init__("coding", "Software Engineering & Compilation Agent")
        self.dev = dev_engine

    def execute_task(self, payload: Dict[str, Any]) -> str:
        action = payload.get("action", "").lower().strip()
        code = payload.get("code", "").strip()
        script_path = payload.get("script_path", "").strip()

        self.logger.info(f"CodingAgent executing action: {action}")

        # If a sandbox executor class exists (Phase 3), delegate process isolation to it
        use_sandbox = payload.get("sandbox", True)
        
        if use_sandbox:
            try:
                from sandbox.executor import SandboxExecutor
                # Dev-initiated code runs are trusted by definition, so host
                # subprocess fallback is explicitly opted in here. The sandbox
                # itself still refuses host execution by default for other callers.
                executor = SandboxExecutor(allow_host_fallback=True)
                if action == "run_script" and script_path:
                    return executor.run_python_script(script_path)
                elif action == "run_code" and code:
                    return executor.run_python_code(code)
            except ImportError:
                self.logger.warning("SandboxExecutor unavailable. Falling back to host execution.")
            except Exception as se:
                return f"Sandbox execution failure: {se}"

        # Fallback to legacy developer engine host execution if sandbox isn't used or loaded
        if self.dev:
            if action == "build" or action == "compile":
                import py_compile
                try:
                    py_compile.compile(script_path, doraise=True)
                    return f"Successfully compiled {script_path}."
                except Exception as compile_err:
                    return f"Compilation failed: {compile_err}"
            elif action == "execute" and script_path:
                return self.dev.execute_terminal_command(f"python {script_path}")
            elif action == "explain" or action == "project_explainer":
                return self.dev.explain_project()
            elif action == "repo_analyzer":
                return self.dev.analyze_repository()
            elif action == "bug_hunter":
                return self.dev.audit_repository()
            elif action == "test_generator":
                return self.dev.generate_tests()
        
        return "Developer operations unavailable or command unrecognized."

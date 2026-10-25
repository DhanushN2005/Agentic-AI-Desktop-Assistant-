import os
import sys
import shlex
import subprocess
import shutil
import webbrowser
import re
from utils.config import Config
import logging

class DeveloperEngine:
    DANGER_CMDS = ["rm ", "del ", "format ", "rmdir /s", ">", "mkfs", "rd /s"]

    def __init__(self, orchestrator):
        self.flexie = orchestrator
        self.brain = orchestrator.brain
        self.vision = orchestrator.vision

    def execute_terminal(self, cmd: str) -> str:
        """Executes terminal command and returns a speech-friendly summary of the result."""
        # Security check - SafetyGuard + DangerGate
        try:
            from core.safety import SafetyGuard
            from core.danger_gate import DangerGate
            if not SafetyGuard().validate(cmd):
                return "Blocked by safety guard: command contains dangerous patterns."
            gate = DangerGate()
            if gate.detect(cmd):
                if not self.flexie.voice.confirm(f"The command '{cmd}' might be dangerous. Do you still want to run it?"):
                    return "Command execution cancelled for safety."
        except Exception as _e:
            logging.debug("[engines/developer.py:27] Swallowed exception: %s: %s", type(_e).__name__, _e)
        # Legacy danger check
        if any(d in cmd.lower() for d in self.DANGER_CMDS):
            if not self.flexie.voice.confirm(f"The command '{cmd}' might be dangerous. Do you still want to run it?"):
                return "Command execution cancelled for safety."

        # No shell: reject chaining/substitution, run a single argv without shell.
        if re.search(r"&&|\|\||;|\||`|[$][(]", cmd):
            return "Blocked: chained commands, pipes and command substitution are not allowed here. Use one simple command."
        try:
            argv = shlex.split(cmd, posix=(os.name != "nt"))
        except ValueError as _e:
            logging.debug("[engines/developer.py:shlex] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"Could not parse the command: {_e}"
        if not argv:
            return "No command to run."
        try:
            result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output:
                    return f"Command '{cmd}' executed successfully with no visible output."
                
                # If output is long or technical, summarize for speech
                if len(output) > 150 or not output.replace(" ", "").isalnum():
                    summary = self.flexie.brain.ask(f"Summarize this terminal output in one simple conversational sentence for speech: {output[:1000]}")
                    return f"The command succeeded. Briefly: {summary}"
                return f"Command output: {output}"
            else:
                error = result.stderr.strip()
                summary = self.flexie.brain.ask(f"Explain this terminal error in one simple conversational sentence for speech: {error[:500]}")
                return f"The command failed. {summary}"
        except Exception as e:
            logging.debug("[engines/developer.py:49] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I failed to execute the terminal command due to an internal error: {str(e)}"

    def get_git_status(self) -> str:
        """Returns a conversational summary of git status."""
        try:
            status = subprocess.check_output(["git", "status", "--short"], text=True).strip()
            if not status:
                return "Your Git repository is clean. Everything is up to date."
            
            summary = self.flexie.brain.ask(f"Summarize this git status short output into a natural sentence about what files changed: {status}")
            return f"Here is your git status: {summary}"
        except Exception as _e:
            logging.debug("[engines/developer.py:61] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return "Dhanush, it looks like the current folder is not a Git repository, or Git is not initialized here."

    def get_git_diff_summary(self) -> str:
        """Returns a conversational summary of recent changes."""
        try:
            diff = subprocess.check_output(["git", "diff", "--stat"], text=True).strip()
            if not diff:
                return "There are no recent changes to report in your repository."
            
            summary = self.flexie.brain.ask(f"Summarize these git changes based on the file stats in one natural sentence: {diff}")
            return f"Recent changes summary: {summary}"
        except Exception as _e:
            logging.debug("[engines/developer.py:73] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return "I couldn't retrieve a Git diff for this project."

    def run_python_script(self, file_path: str) -> str:
        """Executes a python script and speaks the result or error summary."""
        if not os.path.exists(file_path):
            return f"I couldn't find the Python file at {file_path}."
        
        try:
            res = subprocess.run([sys.executable, file_path], capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                output = res.stdout.strip()
                if not output:
                    return f"The script {os.path.basename(file_path)} ran successfully but produced no output."
                
                summary = self.brain.ask(f"Summarize this python script output for speech in one sentence: {output[:1000]}")
                return f"Script execution successful. Result: {summary}"
            else:
                # Use brain to summarize error
                summary = self.brain.summarize_error(res.stderr)
                return f"The script failed to run. Based on the logs, {summary}"
        except Exception as e:
            logging.debug("[engines/developer.py:94] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"An error occurred while trying to run the script: {str(e)}"

    def debug_screen(self) -> str:
        """Vision-powered debugger. Analyzes the screen for code errors."""
        self.flexie.speak("Analyzing your screen for potential code issues or terminal errors...")
        prompt = (
            "I am showing you a screenshot of a developer's workspace. "
            "Please look for any error messages in terminals, IDEs (like VS Code), or browsers. "
            "Explain what the error is in simple terms and suggest a quick fix. "
            "Speak directly to Dhanush."
        )
        return self.vision.analyze_screen(self.brain, prompt)

    def _get_project_files_summary(self, max_files=40):
        cwd = os.getcwd()
        files = []
        for root, dirs, filenames in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'venv', 'node_modules', 'browser_session']]
            for f in filenames[:10]:
                if f.startswith("."):
                    continue  # never leak dotfiles (.env) into LLM prompts
                if f.endswith(('.py', '.js', '.html', '.css', '.md', '.json', '.ts', '.jsx', '.tsx')):
                    files.append(os.path.join(os.path.relpath(root, cwd), f))
            if len(files) > max_files: break
        return os.path.basename(cwd), "\n".join(files)

    def explain_project(self) -> str:
        """Scans current directory and explains the project structure in multiple views."""
        try:
            cwd_name, file_list = self._get_project_files_summary()
            self.flexie.speak("Analyzing the project architecture and module flow...")
            prompt = (
                f"I am analyzing the directory: {cwd_name}. "
                f"Here are some files in the project:\n{file_list}\n\n"
                "Explain this project. Provide the output in exactly 3 sections using markdown headers:\n"
                "## Beginner View (Simple purpose)\n"
                "## Intermediate View (Module interaction, Request flow, DB flow)\n"
                "## Architect View (Architecture overview, Sequence flow, Dependencies)"
            )
            res = self.brain.ask(prompt)
            if not res: return "I'm sorry, I couldn't generate the project explanation. The AI model might be offline or out of memory."
            
            with open("flexie_project_explanation.md", "w", encoding="utf-8") as f:
                f.write(res)
            return "I have analyzed the project and saved a detailed multi-level explanation to flexie_project_explanation.md in your project folder."
        except Exception as e:
            logging.debug("[engines/developer.py:138] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I had trouble explaining the project: {e}"

    def analyze_repository(self) -> str:
        """Deep analysis of repository architecture and dependencies."""
        try:
            cwd_name, file_list = self._get_project_files_summary(max_files=100)
            self.flexie.speak("Scanning repository tree and dependencies...")
            prompt = (
                f"I am analyzing the repository: {cwd_name}. "
                f"Here is the file tree:\n{file_list}\n\n"
                "Generate a REPOSITORY ANALYSIS REPORT. "
                "Include these sections:\n"
                "- Detected Frameworks & APIs\n"
                "- Architecture Style\n"
                "- Component Map\n"
                "- Execution Flow\n"
                "- Dependency Graph\n"
                "- Risk Areas\n"
            )
            res = self.brain.ask(prompt)
            if not res: return "I'm sorry, I couldn't generate the architecture report. The AI model might be offline or the context was too large."
            
            with open("flexie_architecture_report.md", "w", encoding="utf-8") as f:
                f.write(res)
            return "I have completed the repository analysis. The full architectural report has been saved to flexie_architecture_report.md."
        except Exception as e:
            logging.debug("[engines/developer.py:164] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I had trouble analyzing the repository: {e}"

    def audit_repository(self) -> str:
        """Hunts for bugs, dead code, and architecture violations."""
        try:
            cwd_name, file_list = self._get_project_files_summary(max_files=50)
            self.flexie.speak("Auditing repository for bugs and vulnerabilities...")
            prompt = (
                f"I am auditing the repository: {cwd_name}. "
                f"Files:\n{file_list}\n\n"
                "Based on typical patterns for these files, identify potential bugs, dead code, circular dependencies, race conditions, missing exception handling, and architecture violations.\n"
                "Group findings by Severity (Critical, High, Medium, Low).\n"
                "For each bug, provide: Location, Explanation, Impact, Suggested Fix."
            )
            res = self.brain.ask(prompt)
            if not res: return "I'm sorry, the bug hunt failed. The AI model might be offline or out of memory."
            
            with open("flexie_bug_report.md", "w", encoding="utf-8") as f:
                f.write(res)
            return "I have finished auditing the codebase. A full severity breakdown and bug report has been saved to flexie_bug_report.md."
        except Exception as e:
            logging.debug("[engines/developer.py:185] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I had trouble auditing the repository: {e}"

    def generate_tests(self) -> str:
        """Generates unit tests for the current project."""
        try:
            cwd_name, file_list = self._get_project_files_summary(max_files=30)
            self.flexie.speak("Generating test suites for your project...")
            prompt = (
                f"Project: {cwd_name}\n"
                f"Files:\n{file_list}\n\n"
                "Generate a python unit test suite (pytest format) for the core logic you can infer from these files. "
                "Provide the raw code block for `test_main.py`.\n"
                "After the code block, provide a Coverage Report summary showing: Functions Covered, Missing Tests, Critical Paths."
            )
            res = self.brain.ask(prompt)
            if not res: return "I'm sorry, I couldn't generate tests. The AI model might be offline or out of memory."
            
            # Extract code block
            match = re.search(r"```(?:python)?\s*(.*?)\s*```", res, re.DOTALL)
            if match:
                code = match.group(1).strip()
                os.makedirs("tests", exist_ok=True)
                with open("tests/test_main.py", "w", encoding="utf-8") as f:
                    f.write(code)
                return "I have generated the unit tests and saved them as test_main.py in the tests folder. You can run them using pytest."
            
            return "I generated the tests but couldn't parse the code block correctly. Please try again."
        except Exception as e:
            logging.debug("[engines/developer.py:213] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I had trouble generating tests: {e}"

    def autonomous_build(self, user_request: str, autonomous: bool = False) -> str:
        """Plans, creates, configures IDE extensions, and implements an end-to-end project.
        
        Generates:
        - Multi-phase project plan & architecture (saved to PLAN.md)
        - .vscode/settings.json (with Cline & Roo Code free AI model bridges: Ollama, Groq, OpenRouter)
        - .vscode/extensions.json (recommending Antigravity, Cline, Python, Live Server)
        - .vscode/tasks.json (for one-click build and run)
        - All implementation source files with error-correction loop
        - Automatic launch in VS Code and Browser / Runtime
        """
        self.flexie.speak("Initiating Autonomous End-to-End Build Sequence. Planning your architecture now...")
        is_auto = autonomous or getattr(self.flexie, 'current_mode', '') in ('hacker', 'developer')
        
        # 1. End-to-End Architecture & Multi-Step Project Planning
        plan_prompt = f"""
        User Request: {user_request}
        Target Environment: Windows, Multi-step End-to-End Project (Python / HTML / CSS / JS)
        
        Plan a complete project for this request.
        Include all necessary files for a working app plus a PLAN.md documentation file.
        Respond ONLY with a valid JSON object in this format:
        {{
            "folder_name": "ProjectName",
            "overview": "Short description of project and technical design",
            "phases": [
                {{"phase": 1, "title": "Scaffolding & Architecture", "details": "Folder structure & plan"}},
                {{"phase": 2, "title": "Core Implementation", "details": "Application business logic and UI"}},
                {{"phase": 3, "title": "IDE & Assistant Tooling", "details": "VS Code, Cline configuration and task setups"}},
                {{"phase": 4, "title": "Testing & Launch", "details": "Verification and live execution"}}
            ],
            "files": [
                {{"name": "relative/path/to/file.ext", "description": "purpose of file"}}
            ],
            "main_file": "relative/path/to/main_file.ext",
            "run_command": "command to run the project (e.g. python main.py or index.html)"
        }}
        """
        
        try:
            raw_plan = self.brain.ask(plan_prompt, system_override="You are a Lead Software Architect. Respond only with raw JSON.", use_rag=False)
            start, end = raw_plan.find('{'), raw_plan.rfind('}')
            if start == -1 or end == -1: return "I failed to generate an architecture project plan."
            
            import json
            plan = json.loads(raw_plan[start:end+1])
            folder_name = plan.get("folder_name", "Flexie_Generated_Project")
            files = plan.get("files", [])
            phases = plan.get("phases", [])
            overview = plan.get("overview", user_request)
            
            # Determine base directory
            base_dir = self.flexie.ctx.last_path if getattr(self.flexie.ctx, 'last_path', None) and os.path.isdir(self.flexie.ctx.last_path) else Config.FOLDER_SHORTCUTS.get("desktop")
            folder = os.path.join(base_dir, folder_name)
            
            # Phase 1: Directory & Plan creation
            os.makedirs(folder, exist_ok=True)
            if hasattr(self.flexie, 'ctx'):
                self.flexie.ctx.update(last_path=folder)
            
            self.flexie.speak(f"Phase 1 complete: Scaffolded '{folder_name}'. Writing project specification...")
            
            # Generate and write PLAN.md
            plan_md_content = f"# {folder_name} - Project Specification\n\n"
            plan_md_content += f"**Overview:** {overview}\n\n## Multi-Step Roadmap\n"
            for p in phases:
                plan_md_content += f"- **Phase {p.get('phase')}: {p.get('title')}** — {p.get('details')}\n"
            plan_md_content += "\n## File Manifest\n"
            for f_info in files:
                plan_md_content += f"- `{f_info['name']}`: {f_info['description']}\n"
            plan_md_content += "\n## Autonomous Assistant Configuration\n"
            plan_md_content += "This project includes pre-configured `.vscode` settings for AI coding assistants (Cline, Roo Code, Antigravity) with free local Ollama (`http://localhost:11434/v1`) and OpenRouter/Groq model bridges.\n"
            
            with open(os.path.join(folder, "PLAN.md"), "w", encoding="utf-8") as f:
                f.write(plan_md_content)

            # Phase 2: IDE & Assistant Extensions Configuration (.vscode)
            vscode_dir = os.path.join(folder, ".vscode")
            os.makedirs(vscode_dir, exist_ok=True)
            
            # .vscode/extensions.json
            extensions_json = {
                "recommendations": [
                    "saoudrizwan.claude-dev",       # Cline
                    "rooveterinaryinc.roo-cline",   # Roo Code
                    "ms-python.python",             # Python
                    "ritwickdey.LiveServer",        # Live Server
                    "esbenp.prettier-vscode"        # Prettier
                ]
            }
            with open(os.path.join(vscode_dir, "extensions.json"), "w", encoding="utf-8") as f:
                json.dump(extensions_json, f, indent=4)
                
            # .vscode/settings.json - pre-wire free model configurations for Cline/Roo Code
            settings_json = {
                "editor.formatOnSave": True,
                "cline.apiProvider": "ollama",
                "cline.ollamaModelId": "qwen2.5-coder:7b",
                "cline.ollamaBaseUrl": "http://localhost:11434",
                "roo-cline.apiProvider": "ollama",
                "roo-cline.ollamaModelId": "qwen2.5-coder:7b",
                "roo-cline.ollamaBaseUrl": "http://localhost:11434",
                "files.exclude": {
                    "**/__pycache__": True,
                    "**/.git": True
                }
            }
            with open(os.path.join(vscode_dir, "settings.json"), "w", encoding="utf-8") as f:
                json.dump(settings_json, f, indent=4)

            # .vscode/tasks.json - automated build/run task
            tasks_json = {
                "version": "2.0.0",
                "tasks": [
                    {
                        "label": "Run Application",
                        "type": "shell",
                        "command": plan.get("run_command", "python main.py"),
                        "group": {"kind": "build", "isDefault": True},
                        "presentation": {"reveal": "always", "panel": "new"}
                    }
                ]
            }
            with open(os.path.join(vscode_dir, "tasks.json"), "w", encoding="utf-8") as f:
                json.dump(tasks_json, f, indent=4)

            # Phase 3: Code Implementation Loop
            self.flexie.speak(f"Phase 2 complete: Configured VS Code and AI assistant extensions. Now implementing source files...")
            
            for f_info in files:
                name = f_info["name"]
                desc = f_info["description"]
                
                # Skip if already created (e.g. PLAN.md)
                if os.path.exists(os.path.join(folder, name)) and name == "PLAN.md":
                    continue
                
                code_prompt = f"Project: {user_request}\nFile: {name} ({desc})\n\nWrite the complete, functional, production-ready source code for {name}. Output ONLY the code, with no conversational remarks or web search summaries."
                code = self.brain.ask(code_prompt, system_override="You are a Senior Full-Stack Software Engineer. Output ONLY valid, working source code without conversational text or search results.", use_rag=False)
                
                # Check for DuckDuckGo web search fallback pollution
                if code.startswith("Based on my web search") or "I couldn't find a clear enough summary" in code:
                    code = self.brain.ask(f"Write standard valid code for {name} ({desc}):\n", system_override="Provide only raw source code.", use_rag=False)

                # Extract inside code fence if present
                if "```" in code:
                    m = re.search(r"```(?:[a-zA-Z0-9_\-\+]*\n)?(.*?)```", code, re.DOTALL)
                    if m:
                        code = m.group(1)
                    else:
                        code = re.sub(r"```[a-zA-Z0-9_\-\+]*\n?", "", code).replace("```", "")
                
                fpath = os.path.join(folder, name)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(code.strip())
                
                self.flexie.logger.info(f"Autonomous Developer: Created {name}")
            
            self.flexie.speak(f"Finished writing {len(files)} files. Verifying code stability...")

            # Phase 4: Verification & Self-Correction
            verify_failed = []
            for f_info in files:
                fpath = os.path.join(folder, f_info["name"])
                if not os.path.exists(fpath) or os.path.getsize(fpath) == 0:
                    verify_failed.append(f_info["name"])
            if verify_failed:
                return f"Build incomplete - missing/empty: {', '.join(verify_failed)}"

            # Auto-run sandbox verification if Python
            try:
                from sandbox.executor import SandboxExecutor
                main_f = plan.get("main_file")
                if main_f and main_f.endswith(".py"):
                    test_path = os.path.join(folder, main_f)
                    if os.path.exists(test_path):
                        ex = SandboxExecutor(timeout=15, allow_host_fallback=True)
                        run_out = ex.run_python_script(test_path)
                        self.flexie.logger.info(f"Autonomous build run output: {run_out[:500]}")
                        if "Execution Failure" in run_out or "Error" in run_out:
                            fix = self.brain.ask(f"Fix this python error and return ONLY corrected code:\n{run_out[:1000]}\n\nCode:\n{open(test_path, encoding='utf-8').read()[:2000]}", use_rag=False)
                            if "```" in fix:
                                m = re.search(r"```(?:python)?\s*(.*?)\s*```", fix, re.DOTALL)
                                if m: fix = m.group(1)
                            with open(test_path, "w", encoding="utf-8") as f: f.write(fix.strip())
                            self.flexie.logger.info("Autonomous build: self-corrected main file")
            except Exception as ve:
                self.flexie.logger.warning(f"Autonomous verify loop: {ve}")

            # Phase 5: Launch in VS Code with Cline/Antigravity integration
            def _launch_in_vscode(target_dir):
                opened = False
                try:
                    res = self.flexie.files.open_item("vscode", target_path=target_dir)
                    if "Opening" in res:
                        opened = True
                except Exception as _e:
                    logging.debug("[engines/developer.py] open_item vscode failed: %s", _e)
                if not opened:
                    try:
                        code_cmd = shutil.which("code") or r"C:\Users\Dhanush\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd"
                        if os.path.exists(code_cmd):
                            if code_cmd.lower().endswith(".cmd") or code_cmd.lower().endswith(".bat"):
                                subprocess.Popen(["cmd.exe", "/c", code_cmd, target_dir], shell=False)
                            else:
                                subprocess.Popen([code_cmd, target_dir], shell=False)
                            opened = True
                        else:
                            os.startfile(target_dir)
                            opened = True
                    except Exception as _e:
                        logging.debug("[engines/developer.py] VS Code fallback failed: %s", _e)
                return opened

            _launch_in_vscode(folder)
            self.flexie.speak("Opened project and extension configurations in VS Code.")

            # Phase 6: Auto-launch Web or Python Application
            main_f = plan.get("main_file")
            has_html = any(f.get("name", "").endswith(".html") for f in files) or os.path.exists(os.path.join(folder, "index.html"))
            
            if has_html:
                index_path = os.path.join(folder, "index.html")
                if not os.path.exists(index_path):
                    for root_dir, _, fs in os.walk(folder):
                        for f in fs:
                            if f.endswith(".html"):
                                index_path = os.path.join(root_dir, f)
                                break
                        if os.path.exists(index_path):
                            break
                if os.path.exists(index_path):
                    try:
                        webbrowser.open(f"file:///{os.path.abspath(index_path).replace(os.sep, '/')}")
                        self.flexie.speak("Launched your application in the browser.")
                        return f"Autonomous project build complete at {folder}. Multi-phase plan created, VS Code extensions configured, and app launched in browser."
                    except Exception as _be:
                        logging.debug("Browser launch failed: %s", _be)

            if main_f and main_f.endswith(".py"):
                script_path = os.path.join(folder, main_f)
                req_path = os.path.join(folder, "requirements.txt")
                if os.path.exists(req_path):
                    try:
                        subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path], capture_output=True, timeout=60)
                    except Exception as _re:
                        logging.debug("Pip install failed: %s", _re)
                return self.run_python_script(script_path)

            return f"Autonomous project build complete at {folder} - {len(files)} files verified and opened in VS Code."
            
        except Exception as e:
            logging.debug("[engines/developer.py:332] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"The autonomous build failed: {e}"

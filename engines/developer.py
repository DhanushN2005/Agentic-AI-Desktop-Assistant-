import os
import sys
import subprocess
import re
from utils.config import Config

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
            if gate.is_dangerous(cmd):
                if not self.flexie.voice.confirm(f"The command '{cmd}' might be dangerous. Do you still want to run it?"):
                    return "Command execution cancelled for safety."
        except: pass
        # Legacy danger check
        if any(d in cmd.lower() for d in self.DANGER_CMDS):
            if not self.flexie.voice.confirm(f"The command '{cmd}' might be dangerous. Do you still want to run it?"):
                return "Command execution cancelled for safety."

        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
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
            return f"I failed to execute the terminal command due to an internal error: {str(e)}"

    def get_git_status(self) -> str:
        """Returns a conversational summary of git status."""
        try:
            status = subprocess.check_output(["git", "status", "--short"], text=True).strip()
            if not status:
                return "Your Git repository is clean. Everything is up to date."
            
            summary = self.flexie.brain.ask(f"Summarize this git status short output into a natural sentence about what files changed: {status}")
            return f"Here is your git status: {summary}"
        except:
            return "Dhanush, it looks like the current folder is not a Git repository, or Git is not initialized here."

    def get_git_diff_summary(self) -> str:
        """Returns a conversational summary of recent changes."""
        try:
            diff = subprocess.check_output(["git", "diff", "--stat"], text=True).strip()
            if not diff:
                return "There are no recent changes to report in your repository."
            
            summary = self.flexie.brain.ask(f"Summarize these git changes based on the file stats in one natural sentence: {diff}")
            return f"Recent changes summary: {summary}"
        except:
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
                if f.endswith(('.py', '.js', '.html', '.css', '.md', '.env', '.json', '.ts', '.jsx', '.tsx')):
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
            return f"I had trouble generating tests: {e}"

    def autonomous_build(self, user_request: str) -> str:
        """Plans, creates, and implement a full mini-project based on description."""
        self.flexie.speak("Initiating Autonomous Build Sequence. Planning your project now...")
        
        # 1. Project Planning
        plan_prompt = f"""
        User Request: {user_request}
        Target Environment: Windows, Python/HTML/JS
        
        Plan a mini-project for this request. 
        Respond ONLY with a JSON object in this format:
        {{
            "folder_name": "string",
            "files": [
                {{"name": "relative/path/to/file.ext", "description": "short purpose"}}
            ],
            "main_file": "relative/path/to/main_file.ext"
        }}
        """
        
        try:
            raw_plan = self.brain.ask(plan_prompt, system_override="You are a Lead Software Architect. Respond only with raw JSON.")
            # Simple extraction
            start, end = raw_plan.find('{'), raw_plan.rfind('}')
            if start == -1 or end == -1: return "I failed to generate a project plan."
            
            import json
            plan = json.loads(raw_plan[start:end+1])
            folder_name = plan.get("folder_name", "Flexie_Generated_Project")
            files = plan.get("files", [])
            
            # Determine base directory from context memory, or default to desktop
            base_dir = self.flexie.ctx.last_path if getattr(self.flexie.ctx, 'last_path', None) and os.path.isdir(self.flexie.ctx.last_path) else Config.FOLDER_SHORTCUTS.get("desktop")
            folder = os.path.join(base_dir, folder_name)
            
            # Create folder
            os.makedirs(folder, exist_ok=True)
            self.flexie.speak(f"Project folder '{folder_name}' created. Now writing code...")
            
            # 2. File Implementation
            for f_info in files:
                name = f_info["name"]
                desc = f_info["description"]
                
                code_prompt = f"Project: {user_request}\nFile: {name} ({desc})\n\nWrite the full, working implementation for this file. Include comments. Respond ONLY with code."
                code = self.brain.ask(code_prompt, system_override="You are a Senior Developer. Provide only the source code.")
                
                # Strip markdown blocks if any
                if "```" in code:
                    code = re.sub(r"```[a-zA-Z]*\n", "", code).replace("```", "")
                
                fpath = os.path.join(folder, name)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(code.strip())
                
                self.flexie.logger.info(f"Autonomous Developer: Created {name}")
            
            self.flexie.speak(f"Finished writing {len(files)} files. Your project is ready in the '{folder_name}' directory.")
            
            # 3. Open in Coder (VS Code)
            if self.flexie.voice.confirm("Would you like me to open this project in VS Code?"):
                self.flexie.files.open_item("vscode", target_path=folder)
            
            # 4. Attempt Run if Python
            main_f = plan.get("main_file")
            if main_f and main_f.endswith(".py"):
                if self.flexie.voice.confirm(f"Should I try to run the main script {main_f}?"):
                    return self.run_python_script(os.path.join(folder, main_f))
                    
            return "Autonomous project build complete."
            
        except Exception as e:
            return f"The autonomous build failed: {e}"

"""Planning & Specification Engine for autonomous Dev Assistant projects.

Generates PLAN.md, ACCEPTANCE.md, and AGENTS.md.
Includes clarification for vague requests, template matching, structured JSON
generation with repair prompt retry, and built-in fallback plans.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils.config import Config

logger = logging.getLogger("flexie.jobs.planner")

# Standard 5-phase breakdown
STANDARD_PHASES = [
    "scaffold",
    "core_logic",
    "ui",
    "tests_and_lint",
    "verify_and_launch",
]

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "templates",
)


@dataclass
class ProjectFileSpec:
    name: str
    purpose: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class ProjectSpec:
    title: str
    stack: str
    summary: str
    run_command: str
    test_command: str
    files: List[ProjectFileSpec] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    phases: List[str] = field(default_factory=lambda: list(STANDARD_PHASES))
    template_used: Optional[str] = None
    assumptions_made: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "stack": self.stack,
            "summary": self.summary,
            "run_command": self.run_command,
            "test_command": self.test_command,
            "files": [f.to_dict() for f in self.files],
            "dependencies": self.dependencies,
            "acceptance_criteria": self.acceptance_criteria,
            "phases": self.phases,
            "template_used": self.template_used,
            "assumptions_made": self.assumptions_made,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectSpec:
        raw_files = data.get("files", [])
        files = [
            f if isinstance(f, ProjectFileSpec) else ProjectFileSpec(f.get("name", "app.py"), f.get("purpose", ""))
            for f in raw_files
        ]
        return cls(
            title=data.get("title", "Autonomous Project"),
            stack=data.get("stack", "python"),
            summary=data.get("summary", ""),
            run_command=data.get("run_command", "python main.py"),
            test_command=data.get("test_command", "pytest"),
            files=files,
            dependencies=data.get("dependencies", []),
            acceptance_criteria=data.get("acceptance_criteria", ["App starts cleanly", "Tests pass"]),
            phases=data.get("phases", list(STANDARD_PHASES)),
            template_used=data.get("template_used"),
            assumptions_made=data.get("assumptions_made", []),
        )


def is_vague_request(request: str) -> bool:
    """Check if the user request lacks both explicit stack and clear purpose."""
    c = request.strip().lower()
    if not c:
        return True

    known_stacks = {
        "python", "flask", "react", "html", "css", "javascript", "js", "vite",
        "node", "nodejs", "cli", "typescript", "ts", "fastapi", "django",
        "express", "nextjs", "next", "vue", "svelte", "angular",
    }
    known_purposes = {
        "calculator", "todo", "game", "dashboard", "api", "scraper", "weather", "chat",
        "converter", "tracker", "blog", "portfolio", "store", "timer", "notes", "quiz",
        "calendar", "calender", "callender", "planner", "scheduler", "events", "holidays",
        "animation", "animated", "interactive", "modern", "responsive", "app", "tool",
        "viewer", "browser", "manager", "monitor", "clock", "watch", "widget", "form",
        "login", "authentication", "auth", "database", "crud", "rest", "graphql",
        "websocket", "messaging", "notification", "search", "filter", "map", "chart",
        "graph", "analytics", "report", "export", "import", "upload", "download",
        "image", "video", "audio", "music", "player", "editor", "preview",
        "markdown", "pdf", "csv", "excel", "json", "xml", "yaml", "toml",
        "website", "landing", "page", "site", "portal", "platform", "system", "service",
        "microservice", "bot", "assistant", "agent", "automation", "crawler",
        "inventory", "expense", "budget", "finance", "invoice", "receipt", "payment",
        "recipe", "food", "fitness", "health", "habit", "workout", "meditation",
        "flashcard", "study", "learning", "exam", "stopwatch", "countdown",
    }

    words = set(re.findall(r"\w+", c))
    has_stack = bool(words & known_stacks)
    has_purpose = bool(words & known_purposes)

    # Known stack or purpose → specific enough regardless of length
    if has_stack or has_purpose:
        return False

    # Generic request markers without substance
    generic_patterns = [
        r"^(build|create|make|code|start)\s+(an?\s+)?(new\s+)?(project|app|application|program|thing)$",
        r"^(build|create|make)\s+something(\s+cool|\s+useful)?$",
    ]
    for pat in generic_patterns:
        if re.match(pat, c):
            return True

    # If the request has at least 5 meaningful words, it's probably specific enough
    meaningful_words = [w for w in words if len(w) > 3]
    if len(meaningful_words) >= 5:
        return False

    # Fewer than 2 words with no known stack/purpose → vague
    return len(c.split()) < 2


def clarify_request(
    request: str,
    voice: Any = None,
    preferences: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[str]]:
    """Clarify vague requests with up to 3 short questions or fallback to safe defaults.

    Returns (refined_request, list_of_assumptions).
    """
    assumptions: List[str] = []
    if not is_vague_request(request):
        return request, assumptions

    pref = preferences or {}
    _cfg_default_stack = getattr(Config, "JOB_DEFAULT_STACK", "python-flask")
    default_stack = pref.get("default_stack", _cfg_default_stack)
    default_purpose = pref.get("default_purpose", "interactive web dashboard")

    # If voice is available and active, ask up to 3 short questions with configurable timeout
    _voice_timeout = getattr(Config, "JOB_VOICE_CLARIFY_TIMEOUT", 20)
    answered = False
    answers: List[str] = []
    if voice and hasattr(voice, "listen") and hasattr(voice, "speak"):
        questions = [
            "What is the main goal or feature of this project?",
            "Which tech stack would you prefer, such as Flask, React, or a CLI tool?",
            "Should it have a web interface or run in the command line?",
        ]
        for q in questions:
            voice.speak(q)
            try:
                ans = voice.listen(timeout=_voice_timeout)
                if ans and len(ans.strip()) > 2 and "timed out" not in ans.lower():
                    answers.append(ans.strip())
                    answered = True
                else:
                    break
            except Exception:
                break

    if answered and answers:
        combined = f"{request} (Goal: {answers[0]}"
        if len(answers) > 1:
            combined += f", Stack: {answers[1]}"
        if len(answers) > 2:
            combined += f", Interface: {answers[2]}"
        combined += ")"
        return combined, assumptions

    # Apply defaults and note assumptions
    assumed_stack = "Python Flask with HTML5 UI" if default_stack == "python-flask" else default_stack
    assumed_purpose = "interactive task and notes manager" if not default_purpose else default_purpose
    assumptions.append(f"Assumed project type: {assumed_purpose}")
    assumptions.append(f"Assumed stack: {assumed_stack}")

    refined = f"Create a {assumed_purpose} using {assumed_stack}"
    logger.info("Clarification fallback applied: %s", refined)
    return refined, assumptions


def match_template(request: str) -> Optional[ProjectSpec]:
    """Find a pre-built template matching request keywords."""
    c = request.lower()
    if not os.path.exists(_TEMPLATES_DIR):
        return None

    # Priority matching
    template_candidates = [
        ("flask_api", ["flask", "rest api", "backend service", "python api", "fastapi", "rest", "backend", "python server"]),
        ("react_vite", ["react", "vite", "jsx", "spa", "frontend", "react app", "reactjs", "react.js"]),
        ("cli_tool", ["cli", "terminal tool", "command line", "argparse", "script tool", "command-line"]),
        ("static_site", ["html", "css", "static website", "landing page", "web page", "static site", "plain html", "vanilla"]),
    ]

    for t_name, keywords in template_candidates:
        if any(kw in c for kw in keywords):
            manifest_path = os.path.join(_TEMPLATES_DIR, t_name, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    files = [ProjectFileSpec(name=f["name"], purpose=f.get("purpose", "")) for f in data.get("files", [])]
                    return ProjectSpec(
                        title=data.get("title", t_name),
                        stack=data.get("stack", t_name),
                        summary=f"Pre-built {t_name} architecture template",
                        run_command=data.get("run_command", "python main.py"),
                        test_command=data.get("test_command", "pytest"),
                        files=files,
                        dependencies=data.get("dependencies", []),
                        acceptance_criteria=data.get("acceptance_criteria", []),
                        phases=list(STANDARD_PHASES),
                        template_used=t_name,
                    )
                except Exception as e:
                    logger.warning("Failed loading template manifest %s: %s", manifest_path, e)
    return None


def get_builtin_fallback_spec(request: str, assumptions: Optional[List[str]] = None) -> ProjectSpec:
    """Bulletproof fallback specification when LLM is offline or invalid."""
    _default_stack = getattr(Config, "JOB_DEFAULT_STACK", "python-flask")
    return ProjectSpec(
        title="Full-Stack Web App",
        stack=_default_stack,
        summary=f"Automated project scaffold for: {request[:60]}",
        run_command="python app.py",
        test_command="pytest",
        files=[
            ProjectFileSpec("app.py", "Main application and REST routes"),
            ProjectFileSpec("requirements.txt", "Project dependencies"),
            ProjectFileSpec("templates/index.html", "Frontend user interface"),
            ProjectFileSpec("static/style.css", "Application styling"),
            ProjectFileSpec("test_app.py", "Automated test suite"),
        ],
        dependencies=["flask>=3.0.0", "pytest>=7.0.0"],
        acceptance_criteria=[
            "Application server starts cleanly without errors",
            "Health check endpoint returns HTTP 200",
            "Web interface renders in browser",
            "Pytest test suite passes",
        ],
        phases=list(STANDARD_PHASES),
        template_used="builtin_fallback",
        assumptions_made=assumptions or [],
    )


def _strip_markdown_fences(raw: str) -> str:
    """Extract clean JSON from LLM output, removing markdown code fences."""
    text = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Try finding first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1].strip()
    return text


def generate_project_spec(
    user_request: str,
    brain: Any = None,
    voice: Any = None,
    preferences: Optional[Dict[str, str]] = None,
) -> ProjectSpec:
    # 1. Template match step on explicit user request
    matched = match_template(user_request)
    if matched:
        logger.info("Using matched template: %s", matched.template_used)
        return matched

    # 2. Clarify step if vague
    refined_request, assumptions = clarify_request(user_request, voice=voice, preferences=preferences)

    # 3. LLM Structured Generation with retry & repair
    if brain and hasattr(brain, "ask"):
        prompt = f"""You are a Principal Software Architect planning a complete, production-quality software project.
User Request: "{refined_request}"

STACK SELECTION RULES (apply in order):
1. NO backend needed (pure UI: calendar, dashboard, calculator, portfolio, clock, quiz, budget, flashcard, etc.)
   → stack="static-web", run_command="open index.html", test_command="none", dependencies=[]
   → Files MUST include: index.html, style.css, app.js
   → May also include: data.js (for static data), additional JS modules
2. Needs Python server / REST API / database → stack="python-flask"
   → Files MUST include: app.py, requirements.txt, templates/index.html, static/style.css, static/app.js, test_app.py
3. Needs React/Node build step → stack="react-vite"
   → Files MUST include: package.json, vite.config.js, index.html, src/main.jsx, src/App.jsx, src/App.css
4. CLI tool (no GUI needed) → stack="python-cli"
   → Files MUST include: main.py, requirements.txt

FILE QUALITY RULES:
- Every file in the "files" list must have a DETAILED purpose (not just "main file" — describe WHAT it implements).
- For a calendar app: app.js must implement "Month/year grid rendering, prev/next navigation, holiday data lookup, event markers, today highlight, year range 2005-2030"
- For a dashboard: app.js must implement "All chart/widget rendering, data updates, interactive filters"
- The HTML file must describe the complete UI structure, not a loading screen.
- Minimum files for any web project: index.html + style.css + app.js (3 files minimum).
- Include a data.js or constants.js for any project with substantial static data (holidays, events, etc.).

ACCEPTANCE CRITERIA RULES:
- Must be specific and testable, not generic.
- For a calendar: "Month grid renders all days correctly", "Prev/Next navigation changes month", "Holidays are highlighted", "Year navigation covers 2005-2030", "Today's date is visually marked"
- For a Flask app: "GET / returns 200", "All API endpoints return JSON", "No unhandled exceptions", "Pytest suite passes"

Return ONLY valid JSON matching this exact schema:
{{
  "title": "Descriptive Project Title",
  "stack": "static-web | python-flask | react-vite | python-cli",
  "summary": "2-3 sentence technical overview describing ALL major features to be implemented",
  "run_command": "exact command to launch the app",
  "test_command": "exact command to run tests (or 'none')",
  "dependencies": ["list", "of", "packages"],
  "files": [
    {{"name": "filename.ext", "purpose": "Detailed description of exactly what this file implements — minimum 15 words"}}
  ],
  "acceptance_criteria": [
    "Specific, testable criterion 1",
    "Specific, testable criterion 2",
    "Specific, testable criterion 3",
    "Specific, testable criterion 4",
    "Specific, testable criterion 5"
  ]
}}
Output ONLY the raw JSON object. No markdown fences, no prose, no comments.
"""
        try:
            raw_response = brain.ask(
                prompt,
                system_override=(
                    "You are a JSON-only software architecture planner. "
                    "Return ONLY a valid JSON object with no markdown, no prose, no code fences. "
                    "Every file must have a detailed purpose of at least 15 words. "
                    "The summary must describe ALL major features. "
                    "Never produce fewer than 3 files for a web project."
                ),
                use_rag=False,
            )
            cleaned = _strip_markdown_fences(raw_response or "")
            data = json.loads(cleaned)
            spec = ProjectSpec.from_dict(data)
            spec.assumptions_made.extend(assumptions)
            if spec.files and spec.run_command:
                return spec
        except Exception as e:
            logger.warning("First LLM planning pass failed (%s). Attempting repair prompt...", e)

            # Repair pass
            repair_prompt = f"""Your previous response was not valid JSON.
Repair this content into strictly valid JSON adhering to the schema:
{raw_response[:800] if 'raw_response' in locals() and raw_response else refined_request}
Output ONLY valid JSON.
"""
            try:
                repair_raw = brain.ask(
                    repair_prompt,
                    system_override="Return strictly valid JSON only.",
                    use_rag=False,
                )
                cleaned_repair = _strip_markdown_fences(repair_raw or "")
                data = json.loads(cleaned_repair)
                spec = ProjectSpec.from_dict(data)
                spec.assumptions_made.extend(assumptions)
                if spec.files:
                    return spec
            except Exception as re_err:
                logger.warning("Repair prompt also failed (%s). Falling back to built-in spec.", re_err)

    # 4. Built-in template fallback
    fallback = get_builtin_fallback_spec(refined_request, assumptions=assumptions)
    return fallback


def write_project_spec_files(spec: ProjectSpec, workspace_dir: str) -> None:
    """Generate PLAN.md, ACCEPTANCE.md, and AGENTS.md inside the job workspace."""
    os.makedirs(workspace_dir, exist_ok=True)

    # 1. PLAN.md
    plan_lines = [
        f"# {spec.title} — Build Plan",
        "",
        f"**Stack:** `{spec.stack}`  ",
        f"**Template:** `{spec.template_used or 'custom'}`  ",
        f"**Run Command:** `{spec.run_command}`  ",
        f"**Test Command:** `{spec.test_command}`  ",
        "",
        "## Summary",
        spec.summary,
        "",
    ]
    if spec.assumptions_made:
        plan_lines.extend(["## Assumptions", *[f"- {a}" for a in spec.assumptions_made], ""])

    plan_lines.extend([
        "## Phase Breakdown",
        "1. **Scaffold**: Initialize directory structure, configurations, and specs",
        "2. **Core Logic**: Implement main application backend/logic components",
        "3. **UI**: Build user interface / CLI interaction layer",
        "4. **Tests & Lint**: Implement automated unit tests and verification suites",
        "5. **Verify & Launch**: Run tests, check runtime health, and launch service",
        "",
        "## File Manifest",
        *[f"- `{f.name}`: {f.purpose}" for f in spec.files],
        "",
        "## Dependencies",
        *([f"- `{dep}`" for dep in spec.dependencies] if spec.dependencies else ["- (Standard library only)"]),
        "",
    ])
    with open(os.path.join(workspace_dir, "PLAN.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(plan_lines))

    # 2. ACCEPTANCE.md
    acceptance_lines = [
        f"# {spec.title} — Acceptance Criteria",
        "",
        "Every criterion below must pass during the verification phase before the job is marked `done`:",
        "",
        *[f"- [ ] {crit}" for crit in spec.acceptance_criteria],
        "",
    ]
    with open(os.path.join(workspace_dir, "ACCEPTANCE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(acceptance_lines))

    # 3. AGENTS.md
    agents_lines = [
        f"# AGENTS.md — Contributor Guidelines for {spec.title}",
        "",
        "This file defines development rules and context for AI coding assistants and developers.",
        "",
        "## Technology Stack",
        f"- Primary stack: **{spec.stack}**",
        f"- Run command: `{spec.run_command}`",
        f"- Test command: `{spec.test_command}`",
        "",
        "## Code Style & Conventions",
        "- Prefer clean, modular functions with descriptive names",
        "- Include comments for non-trivial logic and exports",
        "- Keep dependencies minimal and pinned in configuration files",
        "",
        "## Do-Not-Touch Folders",
        "Never modify or delete files inside these system directories:",
        "- `.git/`",
        "- `venv/`, `.venv/`",
        "- `node_modules/`",
        "- `__pycache__/`",
        "- `.flexie_build.log`",
        "",
        "## Verification Procedure",
        f"1. Run tests: `{spec.test_command}`",
        f"2. Run app: `{spec.run_command}`",
        "3. Confirm acceptance criteria listed in `ACCEPTANCE.md`",
        "",
    ]
    with open(os.path.join(workspace_dir, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(agents_lines))

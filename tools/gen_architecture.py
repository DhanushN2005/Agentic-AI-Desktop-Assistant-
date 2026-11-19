"""Generate docs/ARCHITECTURE.md: full-system map, flow diagrams and per-folder module diagrams.

The module graphs are built from the real code (AST: every ``import``/``from ... import`` found in
each Python file, including lazy imports inside functions), so they cannot drift from the code the
way a hand-drawn diagram does. The runtime flow diagrams are hand-written below (FLOWS) and were
checked against the code when written; re-read them when the flow itself changes.

Usage (from the repository root):
    python tools/gen_architecture.py            # writes docs/ARCHITECTURE.md
"""
from __future__ import annotations

import ast
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".ruff_cache",
             "vision", "workspace", "captures", "data", ".next", "dist", "tests"}

# --------------------------------------------------------------------------------------
# Curated one-line descriptions for modules that have no docstring.
# --------------------------------------------------------------------------------------
DESC = {
    "main": "entry point: installer check, single instance, token, UI process, orchestrator, API server",
    "adapters.brain_adapter": "legacy shim over Brain", "adapters.browser_adapter": "legacy shim over BrowserEngine",
    "adapters.memory_adapter": "legacy shim over memory", "adapters.orchestrator_adapter": "legacy shim over the orchestrator",
    "adapters.telemetry_adapter": "legacy shim over telemetry", "adapters.voice_adapter": "legacy shim over voice",
    "agents.base": "BaseAgent interface for task agents", "agents.browser_agent": "agent that performs browser tasks",
    "agents.coding_agent": "agent that writes/edits code", "agents.memory_agent": "agent for memory store/recall (cached vector store)",
    "agents.planner.planner": "PlannerAgent: breaks a goal into agent tasks", "agents.verification_agent": "agent that checks task outcomes",
    "context.compiler": "ContextCompiler: builds the system prompt from persona + memory (fenced as data)",
    "core.adaptive_router": "learns routes from outcomes; advisory only (never full confidence)",
    "core.agent_arbitrator": "picks which agent handles a task",
    "core.brain": "Brain: LLM provider chain, cache, circuit breaker, streaming, maintenance thread",
    "core.capability_provider": "PluginDiscovery: opt-in plugin loader (allow-listed, by file path)",
    "core.capability_registry": "Capability + CapabilityRegistry: intent -> capability ownership",
    "core.context_memory": "short-term conversational context (last file, app, pending action with TTL)",
    "core.controller": "FlexieController: safety front door (SafetyGuard, DangerGate, approvals, expiry)",
    "core.dag_planner": "DAGPlanner: runs independent steps in parallel (4 threads)",
    "core.danger_gate": "DangerGate: per-clause risky-intent detection and confirmation words",
    "core.event_bus.bus": "Event + EventBus: ordered pub/sub with trace ids",
    "core.execution_graph": "ExecutionGraph: nodes/edges of what ran in a workflow",
    "core.orchestrator": "FlexieOrchestrator: threads, queues, command log, self model, handle_command, run loop",
    "core.router": "IntentRouter: typo fix, NL overrides, compiled triggers -> intent + confidence",
    "core.safety": "SafetyGuard: NFKC-normalised command blocklist and restricted-word filter",
    "core.task_classifier": "TaskType / TaskState / TaskClassifier", "core.task_critic": "TaskCritic: scores a finished step",
    "core.vector_store": "VectorStore: Chroma episodes, background init, prune",
    "core.workflow_executor": "WorkflowExecutor: sequential steps + verify + retry",
    "core.workflow_gatekeeper": "classifies a command as deterministic or needing planning",
    "core.workflow_parser": "WorkflowParser: splits 'A and B then C' into steps",
    "core.telemetry.legacy": "Telemetry: per-command timing log (flexie_telemetry.log)",
    "core.agents": "agent package", "core.handlers": "handler package", "core.inference": "inference engine package",
    "core.skills": "skills package", "core.telemetry": "telemetry package", "core.traces": "traces package",
    "engines.age_calc": "age / next-birthday math", "engines.alarm": "alarms, timers, countdowns, current time",
    "engines.body_metrics": "BMI and unit parsing with plausibility checks", "engines.browser": "BrowserEngine: Playwright on one owner thread",
    "engines.clipboard_mgr": "opt-in clipboard history with secret filtering", "engines.color_info": "colour names, hex, complements",
    "engines.developer": "DeveloperEngine: run/explain/analyze code and repositories", "engines.dictionary": "word definitions and synonyms",
    "engines.email_engine": "EmailEngine: cached IMAP/SMTP, UID-based actions, address validation",
    "engines.facts": "random facts", "engines.files": "FileManager: find/open/rename/delete (exact match, Recycle Bin)",
    "engines.hash_encoder": "hashes and base64/binary encode/decode", "engines.image_gen": "AI image generation",
    "engines.intelligence": "proactive suggestions and briefings", "engines.ip_lookup": "public IP and domain lookup",
    "engines.jokes": "jokes", "engines.json_formatter": "format/validate/flatten JSON", "engines.knowledge": "local file knowledge index (incremental, sensitive files skipped)",
    "engines.long_term_memory": "GlobalMemory: user profile learned from history", "engines.lorem": "lorem ipsum",
    "engines.memory": "MemoryEngine: chat history, reminders, activity log (shared WAL SQLite)", "engines.memory_system": "MemorySystem: conversations, topics, preferences",
    "engines.music": "local music playback (pygame loaded lazily)", "engines.news": "headlines", "engines.password_gen": "password generate/check",
    "engines.pdf_reader": "PDF text extraction (page-capped)", "engines.pomodoro": "pomodoro timer thread", "engines.qrcode_gen": "QR codes",
    "engines.quotes": "quotes", "engines.self_awareness": "SelfAwareness: stored facts, command stats, capability/limitation text",
    "engines.system": "SystemCtrl: volume, brightness, power, app close, window snap, media keys", "engines.text_summarizer": "summarise text/files/URLs",
    "engines.text_tools": "word count, case, extract emails/urls, sort", "engines.tip_calc": "tip and bill split", "engines.uuid_gen": "UUIDs",
    "engines.vision": "VisionEngine: screenshots, vision-model analysis, OCR fallback, camera",
    "engines.weather": "weather (geocode + forecast, cached)", "engines.wiki": "Wikipedia summaries", "engines.youtube_controller": "YouTube control on the shared browser worker",
    "interface.launcher": "helper: ensure_bridge / stop_bridge / open_dashboard for the web dashboard, plus an optional tray + hotkey Launcher that main.py does not start",
    "interface.ui": "PyQt6 floating-orb HUD (separate process): orb, Ctrl+F spotlight, tray, API-keys dialog, approval popup, signed UDP 9886",
    "interface.web_ui_bridge": "web bridge: serves the dashboard page + /static, authenticated WebSocket <-> signed UDP relay",
    "interface.api_server": "FastAPI REST + SSE API (:8768): commands, page assist, approvals, mail, usage",
    "core.settings_service": "settings for the dashboard: masked key hints, validated saves (dashboard counterpart of the Qt keys dialog)",
    "utils.udp_auth": "signed UDP datagrams, per-run token file, registry of UI ports (9888 web bridge)",
    "interface.voice": "VoiceInterface: mic VAD, ASR, TTS (neural + SAPI)",
    "recovery.analyzer": "RecoveryAnalyzer: LLM diagnosis of a failed step (shared instance)",
    "sandbox.executor": "SandboxExecutor: Docker python.exec with resource limits",
    "sdd.engineer": "SDDEngineer: idea -> build plan",
    "utils.config": "Config: env/.env settings, providers, ports, limits", "utils.helpers": "find_executable, is_online, get_numbers",
    "utils.installer": "install missing dependencies on first run", "verification.capability_validator": "CapabilityValidator: checks a capability really took effect (file, app, camera, clipboard)",
    "verification.semantic_validator": "SemanticValidator: checks a step outcome made sense", "verification.strict_validator": "StrictValidator: is the named app actually running",
    "voice.tts_guard": "TTSGuard: drops repeated spoken messages",
}

CLUSTERS_CORE = {
    "Safety and control": ["core.controller", "core.danger_gate", "core.safety", "core.permission_system", "core.plan_text",
                           "core.run_budget", "core.capabilities", "core.capability_provider", "core.capability_registry"],
    "Routing and planning": ["core.router", "core.hybrid_router", "core.adaptive_router", "core.task_classifier", "core.workflow_gatekeeper",
                             "core.workflow_parser", "core.goal_planner", "core.goal_evaluator", "core.dag_planner", "core.workflow_executor",
                             "core.execution_graph", "core.task_critic", "core.agent_arbitrator"],
    "Execution and tools": ["core.tool_registry", "core.agent_executor", "core.agent_loop", "core.atomic_actions", "core.action_command",
                            "core.action_result", "core.coding_tools", "core.browser_and_comm_tools", "core.desktop_control",
                            "core.mcp_adapter", "core.specialists"],
    "LLM and self": ["core.brain", "core.llm_providers", "core.llm_failure", "core.model_hub", "core.persona", "core.self_model"],
    "Memory": ["core.memory_manager", "core.memory_facade", "core.vector_store", "core.context_memory"],
}

# --------------------------------------------------------------------------------------
# Scan
# --------------------------------------------------------------------------------------
mods: dict[str, dict] = {}
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
    for f in sorted(files):
        if not f.endswith(".py") or f in ("conftest.py",):
            continue
        path = os.path.join(dirpath, f)
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        name = rel[:-3].replace("/", ".")
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        try:
            src = open(path, encoding="utf-8").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                imports.add(n.module)
                imports.update(n.module + "." + a.name for a in n.names)
        doc = (ast.get_docstring(tree) or "").strip().split("\n")[0].strip()
        classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")]
        mods[name] = {"path": rel, "doc": doc, "classes": classes, "funcs": funcs, "imports": imports,
                      "lines": src.count("\n") + 1}

NAMES = set(mods)


def resolve(imp: str) -> str | None:
    parts = imp.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in NAMES:
            return cand
    return None


EDGES: dict[str, set[str]] = collections.defaultdict(set)
USED_BY: dict[str, set[str]] = collections.defaultdict(set)
for m, info in mods.items():
    for imp in info["imports"]:
        t = resolve(imp)
        if t and t != m and not t.startswith(m + ".") and not m.startswith(t + "."):
            EDGES[m].add(t)
            USED_BY[t].add(m)


def describe(name: str) -> str:
    info = mods[name]
    if name in DESC:
        return DESC[name]
    if info["doc"]:
        return info["doc"][:110]
    parts = []
    if info["classes"]:
        parts.append("defines " + ", ".join(info["classes"][:3]))
    if info["funcs"]:
        parts.append(", ".join(info["funcs"][:3]))
    return "; ".join(parts) if parts else "package marker"


def pkg_key(name: str) -> str:
    p = name.split(".")
    if p[0] == "core" and len(p) > 2:
        return "core." + p[1]
    if p[0] == "core":
        return "core (root)"
    return p[0]


def nid(name: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name)


def label_text(text: str) -> str:
    return text.replace('"', "'").replace(";", ",").replace("#", "").replace("<", "&lt;").replace(">", "&gt;")


def node(name: str, short: bool = False) -> str:
    base = name.split(".")[-1] + ".py"
    if name.count(".") == 0 and name != "main":
        base = name
    d = label_text(describe(name))
    if short or not d:
        return f'{nid(name)}["{base}"]'
    return f'{nid(name)}["<b>{base}</b><br/>{d[:70]}"]'


def graph(names: list[str], title_dir: str = "LR", extra_edges: list[tuple[str, str]] | None = None, short: bool = False) -> str:
    names = [n for n in names if n in mods]
    S = set(names)
    lines = [f"flowchart {title_dir}"]
    lines += ["    " + node(n, short) for n in names]
    seen = set()
    for n in names:
        for t in sorted(EDGES.get(n, ())):
            if t in S and (n, t) not in seen:
                lines.append(f"    {nid(n)} --> {nid(t)}")
                seen.add((n, t))
    for a, b in (extra_edges or []):
        lines.append(f"    {a} --> {b}")
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def cluster_graph(clusters: dict[str, list[str]], direction: str = "LR") -> str:
    lines = [f"flowchart {direction}"]
    allnames = []
    for i, (title, members) in enumerate(clusters.items()):
        members = [m for m in members if m in mods]
        if not members:
            continue
        lines.append(f'    subgraph sg{i}["{label_text(title)}"]')
        lines += ["        " + node(m) for m in members]
        lines.append("    end")
        allnames += members
    S = set(allnames)
    for n in allnames:
        for t in sorted(EDGES.get(n, ())):
            if t in S:
                lines.append(f"    {nid(n)} --> {nid(t)}")
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def inventory_table(names: list[str]) -> str:
    rows = ["| File | What it does | Lines | Imported by |", "|---|---|---:|---|"]
    for n in names:
        i = mods[n]
        users = sorted(USED_BY.get(n, ()))
        used = ", ".join(u.split(".")[-1] for u in users[:4]) + (f" (+{len(users) - 4})" if len(users) > 4 else "")
        if not users:
            used = "—  (entry point, loaded dynamically, or unused)"
        rows.append(f"| `{i['path']}` | {describe(n).replace('|', '/')} | {i['lines']} | {used} |")
    return "\n".join(rows)


# --------------------------------------------------------------------------------------
# Folder-level map from real edges
# --------------------------------------------------------------------------------------
PKG_EDGES = collections.Counter()
for m, ts in EDGES.items():
    for t in ts:
        a, b = pkg_key(m), pkg_key(t)
        if a != b:
            PKG_EDGES[(a, b)] += 1
PKG_COUNT = collections.Counter(pkg_key(m) for m in mods)


def folder_map() -> str:
    groups = {
        "Entry": ["main", "adapters"],
        "Brain of the system (core)": ["core (root)", "core.handlers", "core.jobs", "core.telemetry", "core.traces", "core.event_bus",
                                       "core.inference", "core.skills", "core.agents"],
        "Capabilities": ["engines", "agents", "sandbox", "context", "recovery", "sdd", "verification", "voice"],
        "Interfaces": ["interface"],
        "Support": ["utils", "evals", "tools", "templates"],
    }
    lines = ["flowchart TD"]
    present = set(PKG_COUNT)
    for i, (title, members) in enumerate(groups.items()):
        members = [m for m in members if m in present]
        lines.append(f'    subgraph g{i}["{title}"]')
        for m in members:
            lines.append(f'        {nid(m)}["{m}<br/>{PKG_COUNT[m]} modules"]')
        lines.append("    end")
    shown = 0
    for (a, b), c in sorted(PKG_EDGES.items(), key=lambda kv: -kv[1]):
        if c >= 2 and a in present and b in present and shown < 70:
            lines.append(f'    {nid(a)} -->|{c}| {nid(b)}')
            shown += 1
    return "```mermaid\n" + "\n".join(lines) + "\n```"


# --------------------------------------------------------------------------------------
# Hand-written flows (checked against the code when written)
# --------------------------------------------------------------------------------------
FLOWS = open(os.path.join(ROOT, "tools", "architecture_flows.md"), encoding="utf-8").read()


def intent_map() -> str:
    """intent -> handler -> engine, parsed from the README table (only files that exist)."""
    rows = []
    try:
        text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    except OSError:
        return ""
    for m in re.finditer(r"^\| \d+ \| `([a-z_]+)` \|[^|]*\|([^|]*)\|", text, re.M):
        intent, files = m.group(1), m.group(2)
        hs = re.findall(r"handlers/([a-z_]+)\.py", files)
        es = re.findall(r"engines/([a-z_]+)\.py", files)
        hs = [h for h in hs if f"core.handlers.{h}" in mods]
        es = [e for e in es if f"engines.{e}" in mods]
        if hs or es:
            rows.append((intent, hs[:1], es[:1]))
    lines = ["flowchart LR", '    D["dispatch_intent<br/>core/handlers/dispatcher.py"]']
    done = set()
    for intent, hs, es in rows[:60]:
        i = "i_" + intent
        lines.append(f'    D --> {i}(["{intent}"])')
        for h in hs:
            lines.append(f'    {i} --> h_{h}["handlers/{h}.py"]')
            for e in es:
                if (h, e) not in done:
                    lines.append(f'    h_{h} --> e_{e}["engines/{e}.py"]')
                    done.add((h, e))
        if not hs:
            for e in es:
                lines.append(f'    {i} --> e_{e}["engines/{e}.py"]')
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def orchestrator_wiring() -> str:
    o = "core.orchestrator"
    targets = sorted(EDGES.get(o, ()))
    groups = collections.defaultdict(list)
    for t in targets:
        groups[pkg_key(t)].append(t)
    lines = ["flowchart LR", f'    {nid(o)}["<b>core/orchestrator.py</b><br/>owns every subsystem"]']
    for i, (g, ts) in enumerate(sorted(groups.items())):
        lines.append(f'    subgraph w{i}["{g}"]')
        lines += ["        " + node(t, short=True) for t in ts]
        lines.append("    end")
        lines.append(f"    {nid(o)} --> w{i}")
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def build() -> str:
    core_root = sorted(n for n in mods if pkg_key(n) == "core (root)")
    handlers = sorted(n for n in mods if pkg_key(n) == "core.handlers" and n != "core.handlers")
    jobs = sorted(n for n in mods if pkg_key(n) == "core.jobs" and n != "core.jobs")
    small_core = {k: sorted(n for n in mods if pkg_key(n) == k) for k in
                  ("core.telemetry", "core.traces", "core.event_bus", "core.inference", "core.skills", "core.agents")}
    engines = sorted(n for n in mods if n.startswith("engines."))
    out = []
    out.append("# Flexie 2.0 — Architecture\n")
    out.append("> Generated by `python tools/gen_architecture.py` from the real code (AST imports and docstrings of every "
               f"Python file: **{len(mods)} modules, {sum(len(v) for v in EDGES.values())} import edges**) plus the hand-written "
               "flows in `tools/architecture_flows.md`. Module diagrams therefore match the code; flow diagrams were checked when "
               "written, so re-read them when behaviour changes. Diagrams use Mermaid (GitHub renders them).\n")
    out.append("**Contents**\n\n1. [Full system map](#1-full-system-map)\n2. [Runtime flows](#2-runtime-flows)\n"
               "3. [Module diagrams per folder](#3-module-diagrams-per-folder)\n4. [Non-Python parts](#4-non-python-parts)\n"
               "5. [File inventory](#5-file-inventory)\n")

    out.append("## 1. Full system map\n")
    out.append("### 1.1 Folders and how they depend on each other\n\nBoxes are folders (module count); arrows are real imports between "
               "folders, labelled with the number of importing modules (edges with 2 or more shown).\n")
    out.append(folder_map() + "\n")
    out.append("### 1.2 Processes, ports and data stores\n")
    out.append(FLOWS.split("<!--SPLIT-->")[0])

    out.append("## 2. Runtime flows\n")
    out.append(FLOWS.split("<!--SPLIT-->")[1])

    out.append("## 3. Module diagrams per folder\n")
    out.append("Arrows point from the importing module to the imported one. Lazy imports inside functions count.\n")
    out.append("### 3.1 `core/` (root modules by area)\n")
    out.append(cluster_graph(CLUSTERS_CORE) + "\n")
    other = [n for n in core_root if not any(n in v for v in CLUSTERS_CORE.values()) and n != "core.orchestrator"]
    out.append("Remaining `core/` root modules:\n")
    out.append(graph(other, "LR") + "\n")
    out.append("### 3.2 `core/orchestrator.py` — what it wires together\n")
    out.append(orchestrator_wiring() + "\n")
    out.append("### 3.3 `core/handlers/` — intent to handler to engine\n\n"
               "The dispatcher picks a handler by intent; handlers receive the orchestrator and call its engines. Mapping below comes "
               "from the command table in the README (only files that exist).\n")
    out.append(intent_map() + "\n")
    out.append("Imports between handler modules and the rest of the system:\n")
    out.append(graph(handlers, "LR", short=True) + "\n")
    out.append("### 3.4 `core/jobs/` — autonomous build jobs\n")
    out.append(graph(jobs, "LR") + "\n")
    for key, title in (("core.telemetry", "3.5 `core/telemetry/`"), ("core.traces", "3.6 `core/traces/`"),
                       ("core.event_bus", "3.7 `core/event_bus/`"), ("core.inference", "3.8 `core/inference/`"),
                       ("core.skills", "3.9 `core/skills/`"), ("core.agents", "3.10 `core/agents/`")):
        names = small_core[key]
        out.append(f"### {title}\n")
        out.append(graph(names, "LR") + "\n")
    out.append("### 3.11 `engines/`\n\nEach engine is a plain class owned by the orchestrator; most have no imports between them. Edges show "
               "where engines share code.\n")
    out.append(graph(engines, "LR", short=True) + "\n")
    out.append("### 3.12 `interface/`, `utils/`, `agents/`, `adapters/`, `context/`, `recovery/`, `sandbox/`, `sdd/`, `voice/`, `evals/`, `tools/`, "
               "`verification/`\n")
    for title, pred in (("interface/", lambda n: n.startswith("interface.")), ("utils/", lambda n: n.startswith("utils.")),
                        ("agents/ and adapters/", lambda n: n.startswith(("agents", "adapters"))),
                        ("context/, recovery/, sandbox/, sdd/, voice/", lambda n: n.split(".")[0] in ("context", "recovery", "sandbox", "sdd", "voice")),
                        ("evals/ and tools/", lambda n: n.split(".")[0] in ("evals", "tools")),
                        ("verification/", lambda n: n.split(".")[0] == "verification")):
        names = sorted(n for n in mods if pred(n))
        if names:
            out.append(f"**{title}**\n")
            out.append(graph(names, "LR") + "\n")

    out.append("## 4. Non-Python parts\n")
    out.append(FLOWS.split("<!--SPLIT-->")[2])

    out.append("## 5. File inventory\n")
    out.append("Every Python module outside `tests/`, with what it does and who imports it. A module with no importers is an entry point, is "
               "loaded dynamically (handlers, plugins, templates) or is unused.\n")
    groups: dict[str, list[str]] = collections.OrderedDict()
    for n in sorted(mods):
        groups.setdefault(n.split(".")[0] if n.split(".")[0] != "core" else (n.split(".")[0] + ("/" + n.split(".")[1] if len(n.split(".")) > 2 else " (root)")), []).append(n)
    for g, names in groups.items():
        out.append(f"<details><summary><b>{g}</b> — {len(names)} files</summary>\n\n{inventory_table(names)}\n\n</details>\n")
    unused = sorted(n for n in mods if not USED_BY.get(n) and n not in ("main",) and not n.startswith(("core.handlers", "evals", "tools", "templates")))
    out.append("### Modules nothing imports\n\nCandidates for review (some are entry points or loaded by name):\n\n" +
               "\n".join(f"- `{mods[n]['path']}` — {describe(n)}" for n in unused) + "\n")
    out.append("\n*Regenerate with `python tools/gen_architecture.py` after changing the code.*\n")
    return "\n".join(out)


if __name__ == "__main__":
    text = build()
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print("docs/ARCHITECTURE.md written:", len(text), "chars,", text.count("```mermaid"), "diagrams")
    sys.exit(0)

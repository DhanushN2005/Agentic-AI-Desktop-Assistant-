# Flexie 2.0 — Autonomous Agentic AI Desktop Assistant

> **Resume:** *Flexie 2.0 — Agentic AI Desktop Assistant — A Windows-native AI agent capable of voice interaction, multi-step task planning, tool execution, desktop automation, memory, web research, code generation, specialist agents, MCP integration, and task verification.*
> **GitHub:** *Flexie 2.0 — Autonomous Agentic AI Desktop Assistant — AI Agent is the core identity; voice, chatbot, automation, browser extension, dev assistant, and desktop control are capabilities of the agent.*

A **zero-config, Windows-native autonomous AI agent** with 30+ free plugins, self-awareness, persistent memory, hybrid agentic routing, browser automation, MCP server integration, specialist multi-agent delegation, REST/SSE API, browser extension, and autonomous dev-assistant build jobs — all running locally on Windows.

**LLM Chain (local-first):** Ollama when available → Groq (main model, then its sibling models on a rate limit) → OpenAI → DeepSeek → Mistral → Gemini (`gemini-flash-latest`, falling back to `gemini-3.8-flash`) → Anthropic → DuckDuckGo fallback. Streaming, VAD, desktop control, self-correction, and cheap-first cascade routing included. Set `FLEXIE_LOCAL_FIRST=0` to skip the local attempt. A failure message is **never** treated as an answer: it is not cached, not written into generated files and not parsed as data (`core/llm_failure.py`). Questions that include a screenshot go only to vision-capable providers.

**Voice:** Edge neural TTS (Jarvis-style, `en-GB-RyanNeural` default) with offline SAPI fallback, natural sentence-batched speech, and markdown/emoji-free spoken prose.

---

## Table of Contents
- [Documentation](#documentation)
- [What Flexie Is](#what-flexie-is)
- [Architecture Overview](#architecture-overview) (ASCII overview and Mermaid diagrams; full set in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))
- [Core Features](#core-features)
- [New in Phases 5–7](#new-in-phases-57)
- [Reliability, Safety & Self-Awareness](#reliability-safety--self-awareness-nov-2026-hardening)
- [All Voice/Text Commands](#all-voicetext-commands)
- [Engines & Stack](#engines--stack)
- [What Flexie Can Do](#what-flexie-can-do)
- [Autonomous Dev Assistant](#autonomous-dev-assistant)
- [Specialist Agents](#specialist-agents)
- [MCP Integration](#mcp-integration)
- [Browser Extension](#browser-extension)
- [REST & SSE API](#rest--sse-api)
- [Automation](#automation)
- [Memory & Intelligence](#memory--intelligence)
- [Voice & Streaming](#voice--streaming)
- [Safety & Permissions](#safety--permissions)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Limitations](#limitations)

## Documentation

All long-form docs live in [`docs/`](docs/README.md):

- [Architecture](docs/ARCHITECTURE.md) — full system map, runtime flow diagrams, per-folder module diagrams, file inventory
- [Features and limits](docs/README_FEATURES.md)
- [OpenJarvis adaptation plan and status](docs/OPENJARVIS_ADAPTATION.md)
- [Fix checklist](docs/FIX_CHECKLIST.md) and the historical [module audit](docs/MODULE_AUDIT_REPORT.md)
- [Benchmark / test report](BENCHMARK_REPORT.md) (kept at the root with `evals/results/`)

---

## What Flexie Is

Flexie is a **desktop-native autonomous AI agent** — *AI Agent is the core identity; voice, chatbot, automation, browser extension, dev assistant, and desktop control are capabilities of the agent.*

It listens to voice (VAD) or keyboard (PyQt6 HUD), understands natural language, **plans multi-step tasks** (`GoalPlanner` + `DAGPlanner`), **executes tools** (`ToolRegistry` 30+ tools, `DesktopControl`, `BrowserEngine`), **remembers** (VectorStore + MemoryManager), **delegates to specialist agents** (Coder, Researcher, System), **connects to any MCP server**, and **verifies** (`GoalEvaluator` + self-correction) — not just chat.

**Resume title:** *Flexie 2.0 — Agentic AI Desktop Assistant* — A Windows-native AI agent capable of voice interaction, multi-step task planning, autonomous build jobs, MCP integration, specialist delegation, browser extension, REST API, IDE integration, and task verification.

**GitHub title:** *Flexie 2.0 — Autonomous Agentic AI Desktop Assistant*

**Not a cloud SaaS** — data stays on your machine. External calls only to free LLM APIs (Groq, Gemini) and free public APIs (weather, news, Wikipedia).

**2,054 tests across 70 test files** (1 skipped) plus a 59-case agent eval and a 158-case routing eval — CI runs pytest and ruff (both blocking) on every push via `.github/workflows/ci.yml`. Tests that touch the build-job system are isolated to a temp folder (`tests/conftest.py`), so a test run no longer writes into your Downloads folder.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ USER INPUT: Voice (VAD) / Keyboard / REST API / WebSocket /     │
│             Browser Extension          (asleep until "Flexie")  │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ CONTROLLER (core/controller.py) — the safety front door         │
│  SafetyGuard (blocklist, NFKC-normalised) → DangerGate          │
│  (per-clause risky-intent check) → approval request with id +   │
│  TTL; the command runs only inside that approval's grant        │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ INTENT ROUTER (core/router.py) ~0.5 ms                          │
│  cached typo-correction → NL_OVERRIDES (197 regex, incl. "about │
│  Flexie itself" questions) → compiled triggers by priority      │
│  → Intent + Confidence; route cache + learned routes in the     │
│  orchestrator                                                   │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ HYBRID ROUTER + MODEL HUB (core/hybrid_router.py, model_hub.py) │
│  Simple → deterministic handler; complex (and/then, low conf.)  │
│  → GoalPlanner (plans are sanitised, RunBudget-limited)         │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ ORCHESTRATOR (core/orchestrator.py)                             │
│  one action worker thread + speech worker; command log; self    │
│  model; WorkflowParser → DAGPlanner → WorkflowExecutor →        │
│  AgentExecutor (observe-act-verify) → Specialists               │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ HANDLERS (49) → ENGINES (43) → DESKTOP / BROWSER / VISION       │
│  ToolRegistry: permission gate, per-tool timeouts, declared     │
│  capabilities, scoped registries for specialists, MCP tools     │
│  (untrusted-output wrapped), path jail for file tools           │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ JOBS SYSTEM (core/jobs/)                                        │
│  Planner → Generator (rejects failure text, retries) → Scaffold │
│  → Verifier (real static checks) → Git; resume/undo             │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ MEMORY + BRAIN                                                  │
│  MemoryManager (SQLite, token-overlap search, secret scrubbing, │
│  TTLs) + VectorStore (Chroma, background init) → ContextCompiler│
│  Brain: provider chain, circuit breaker, cache (TTL, failures   │
│  never cached), streaming, telemetry (tokens/cost/latency)      │
│  REST/SSE API (FastAPI :8768), WebSocket bridge (:8765/:8766)   │
└─────────────────────────────────────────────────────────────────┘
```

**Startup is lazy.** Importing and constructing the orchestrator takes about 1.9 s (it was about 14.5 s): `pygame`, `pyautogui`, `pytesseract`, `playwright` and the model SDKs load on first use (`utils/lazy.py`), and the vector store and the model clients are built in background threads that the first call waits for (bounded at 30 s). Measured on one Windows machine; end-to-end voice latency was not measured.

### Diagrams

**System architecture**

```mermaid
flowchart TD
    subgraph IN["Input"]
        V["Voice (VAD + ASR)<br/>asleep until 'Flexie'"]
        K["Keyboard / PyQt HUD"]
        API["REST API :8768<br/>Browser extension"]
        WS["Web dashboard<br/>WebSocket bridge :8765"]
    end

    V --> CT
    K --> CT
    API --> CT
    WS --> CT

    CT["Controller<br/>SafetyGuard + DangerGate<br/>approval id + TTL"]
    CT --> RT["Intent Router ~0.5 ms<br/>typo fix, 197 NL overrides,<br/>96 trigger intents"]
    RT --> HR["Hybrid Router + Model Hub"]
    HR -->|simple| OR
    HR -->|complex| GP["GoalPlanner<br/>RunBudget"]
    GP --> OR

    OR["Orchestrator<br/>action worker, speech worker,<br/>command log, self model"]
    OR --> HD["Handlers (49)"]
    HD --> EN["Engines (43)"]
    OR --> AE["AgentExecutor<br/>observe - act - verify"]
    AE --> TR["ToolRegistry<br/>permission gate, timeouts,<br/>capabilities, path jail"]
    TR --> MCP["MCP tools<br/>(untrusted output)"]
    OR --> SP["Specialists<br/>Lead / Coder / Researcher / System"]
    OR --> JB["Build jobs<br/>core/jobs"]

    EN --> OS["Windows desktop,<br/>browser (Playwright), vision,<br/>mail, files"]
    TR --> OS

    OR --> BR["Brain<br/>provider chain + cache"]
    BR --> MEM["Memory<br/>MemoryManager + VectorStore"]
    BR --> TEL["Telemetry + traces<br/>data/*.db"]
    OR --> SM["Self model<br/>live answers about Flexie"]
    OR -->|speak| OUT["TTS + UI + API events"]
```

**What happens to one command**

```mermaid
sequenceDiagram
    actor U as User
    participant I as Voice / text / API
    participant C as Controller
    participant R as Router
    participant O as Orchestrator
    participant H as Handler or tool
    participant B as Brain (LLM)

    U->>I: "open chrome and search for cats"
    I->>I: wake word check (asleep? say so once a minute)
    I->>C: command text
    C->>C: SafetyGuard blocklist, DangerGate per clause
    alt risky (delete, send, pay, ...)
        C-->>U: "Say confirm to proceed" (approval id, TTL)
        U->>C: "yes"
        C->>C: approve that request, open one-shot grant
    end
    C->>R: route(command)
    R-->>C: intent + confidence
    C->>O: handle_command
    O->>H: dispatch by intent
    opt open-ended request
        H->>B: ask / ask_stream
        B-->>H: answer (failure text is never used as an answer)
    end
    H-->>O: result
    O->>O: record in command log
    O-->>U: spoken reply + UI text
```

**Risky commands: approval lifecycle**

```mermaid
stateDiagram-v2
    [*] --> Pending: DangerGate flags a clause<br/>(request id + TTL)
    Pending --> Approved: short pure "yes"<br/>("ok but first delete..." is not one)
    Pending --> Rejected: "no" / "cancel"
    Pending --> Expired: TTL passes
    Approved --> Running: command runs inside<br/>a one-shot grant (60 s)
    Running --> Consumed: grant used up
    Consumed --> [*]
    Rejected --> [*]
    Expired --> [*]
```

**Model fallback chain**

```mermaid
flowchart LR
    Q["Prompt"] --> LF{"Local first<br/>and no image?"}
    LF -->|yes| OL["Ollama"]
    LF -->|no| G1
    OL -->|empty or failed| G1
    G1["Groq main model"] -->|429 / error| G2["Groq sibling models<br/>GROQ_FALLBACK_MODELS"]
    G2 --> OP["OpenAI / DeepSeek / Mistral"]
    OP --> GM["Gemini<br/>gemini-flash-latest,<br/>then gemini-3.8-flash"]
    GM --> AN["Anthropic"]
    AN --> FB{"Image attached?"}
    FB -->|yes| VF["Say no vision model answered<br/>(OCR text fallback in the screen handler)"]
    FB -->|no| DD["DuckDuckGo search fallback<br/>(marked as a failure, never cached)"]
    G1 -.->|image| GM
```

**Autonomous build job**

```mermaid
flowchart TD
    REQ["'build me a todo app'"] --> PL["Planner<br/>PLAN.md, ACCEPTANCE.md, AGENTS.md<br/>template match or LLM spec"]
    PL --> WS["Workspace folder + own git repo<br/>under CODE_OUTPUT_DIR"]
    WS --> SC["Scaffold<br/>structure, configs"]
    SC --> GEN["Generator: one file at a time"]
    GEN --> OK{"Model gave real code?"}
    OK -->|"failure text or empty"| RT["Retry after 3 s, then 8 s"]
    RT -->|"still failing"| FAIL["Fail that file with a clear reason<br/>(nothing written, resume later)"]
    RT --> GEN
    OK -->|yes| SYN["Syntax check + one repair pass"]
    SYN --> VER["Verifier<br/>lint, tests, start, smoke test,<br/>static: linked files are real"]
    VER -->|problems| HEAL["Self-heal (up to 3 attempts)"]
    HEAL --> VER
    VER -->|pass| DONE["Done: per-phase git commits,<br/>undo available"]
    FAIL --> CLEAN{"Any files produced?"}
    CLEAN -->|no| RM["Remove the empty folder"]
    CLEAN -->|yes| KEEP["Keep the partial project"]
```

**Vision mode and image download**

```mermaid
flowchart LR
    A["'open vision mode'"] --> B{"vision/node_modules exists?"}
    B -->|no| C["npm ci<br/>(first run, a few minutes)"]
    B -->|yes| D
    C --> D["npm run dev on first free port from 3000"]
    D --> E["Wait until it answers"]
    E --> F["Open in browser<br/>press G for hand gestures"]
    G["'close vision mode'"] --> H["Kill the dev server process tree<br/>(also on Flexie exit)"]

    I["'download 5 images of cats'"] --> J["DuckDuckGo image search<br/>or images on a page URL"]
    J --> K{"Public http(s) address?<br/>(redirects re-checked)"}
    K -->|no| X["Skip"]
    K -->|yes| L["Size, image type and decode checks,<br/>skip duplicates"]
    L --> M["Downloads/Flexie Images/topic-time/"]
```

**Key modules:**
- `core/controller.py` — safety front door: SafetyGuard + DangerGate, per-request approvals, pending-confirmation expiry
- `core/permission_system.py` — 5 levels, approval requests (id, TTL), per-request `grant_scope`, untrusted-content taint per command
- `core/danger_gate.py`, `core/safety.py`, `core/plan_text.py` — risky-intent detection per sentence/clause, command blocklist, clause splitting
- `core/router.py` — TYPO_MAP (cached fuzzy fix, words of 5+ letters), NL_OVERRIDES, compiled triggers, `route()`
- `core/self_model.py` — Flexie's live model of itself (see *Self-awareness*)
- `core/llm_failure.py` — recognises provider-failure text so it is never used as an answer
- `core/hybrid_router.py`, `core/model_hub.py` — simple/complex split, task-based provider choice
- `core/goal_planner.py`, `core/dag_planner.py`, `core/workflow_executor.py`, `core/run_budget.py` — planning, execution, step/time/cycle budgets
- `core/agent_executor.py`, `core/tool_registry.py`, `core/capabilities.py` — tool execution with tri-state verification, timeouts, capability policy (deny-by-default for undeclared capabilities)
- `core/memory_manager.py`, `core/memory_facade.py`, `core/vector_store.py`, `core/context_memory.py` — memory
- `core/brain.py`, `core/llm_providers.py`, `core/inference/` — LLM chain, provider manager, local engines
- `core/telemetry/`, `core/traces/`, `core/event_bus/` — per-call token/cost/latency, traces, ordered events
- `core/mcp_adapter.py` — MCP stdio client, tools default to *confirm* unless listed read-only
- `core/specialists.py` — Lead/Coder/Researcher/System delegation with scoped tools
- `core/jobs/` — autonomous build jobs
- `interface/api_server.py` — FastAPI REST + SSE at :8768; `interface/web_ui_bridge.py` — authenticated WebSocket bridge
- `utils/lazy.py`, `utils/path_jail.py`, `utils/name_index.py`, `utils/sqlite_util.py`, `utils/udp_auth.py` — lazy imports, file jail, bounded file-name index, shared WAL SQLite connection, signed UDP
- `extension/` — Chrome/Edge Manifest V3 extension

---

## Core Features

| Area | Features |
|---|---|
| **Voice** | VAD (RMS + webrtcvad), barge-in, Edge neural TTS + SAPI fallback (text passed via environment, never on the command line), sentence-batched speech, streaming, 8 s stuck watchdog. Flexie sleeps until it hears a wake word ("Flexie") and says so (at most once a minute) instead of silently ignoring speech |
| **Browser** | Playwright persistent context on a single owner thread; navigate/click/fill/scroll (typed values are never logged or spoken), multi-tab research, gmail_read. "open chrome and search for X" opens the search directly in that browser |
| **Files** | create/rename/delete (exact-name match, full path read back before delete, Recycle Bin only), organize desktop with an undo log, bounded name index (`utils/name_index.py`) |
| **Code** | Local search `engines/code_search.py`, generation `handlers/code_gen.py` |
| **Research** | Web search DDG + LLM summary `handlers/research.py` → save to file (report goes to `data/research/`) |
| **Automation** | `engines/automation.py` daily/hourly/interval/once jobs on a `next_run` schedule, persisted to disk; built-in daily briefing; auto-organize is off by default |
| **Memory** | MemoryManager + VectorStore + SelfAwareness facts; secrets scrubbed before storing; TTLs; "forget" reaches every store |
| **Self-awareness** | `core/self_model.py`: answers about what model it runs on, what it just did, why something failed, whether it is awake, what it remembers, what tools and limits it has — from live state, not from the LLM |
| **Safety** | SafetyGuard (NFKC-normalised blocklist, whole-word restricted words), DangerGate (per sentence/clause), PermissionSystem (5 levels, request ids, TTL, one-shot grants), untrusted-content taint, path jail, signed UDP, authenticated bridge/API |
| **Dev Jobs** | Autonomous build jobs: Planner → Scaffold → Generator → Verifier → Git; a failed model call never becomes file content; empty failed workspaces are removed |
| **Specialists** | Lead, Coder, Researcher, System — scoped tools per role, run budgets |
| **MCP** | External MCP stdio/HTTP servers; tools default to confirm; output wrapped as untrusted |
| **Extension** | Chrome/Edge Manifest V3 sidebar, floating pill, context menus, page assist (endpoint allow-list, sender checks) |
| **REST API** | FastAPI :8768, Bearer token, `/command`, `/health`, `/api/flexie/*`, SSE state stream, approvals by request id |
| **Images** | "download 5 images of cats" (web search) or from a page URL — public http(s) only, size/type/decode checks, new folder under `Downloads\Flexie Images` |
| **Vision mode** | "open vision mode" starts the hand-gesture orb UI in `vision/` and opens it in the browser; "close vision mode" stops it |
| **Screen** | screenshot (says where it was saved), analyze/summarize screen through a vision model, OCR text fallback when no vision model answers |
| **Model Hub** | Task-based provider choice, cheap-first cascade, circuit breaker with half-open recovery |
| **Telemetry** | Every LLM call recorded (tokens, cost, latency, failures) in `data/telemetry.db`; traces in `data/traces.db`; `/api/flexie/usage` |

---

## New in Phases 5–7

### Phase 5 — Model Hub & Intelligent Routing
- **Model Hub** (`core/brain.py`) — task-based LLM routing: code tasks → Groq code model, vision → Gemini, chat → cheap-first cascade.
- **Cheap-first cascade** — attempts the cheapest capable model first; promotes to smarter model only on failure or low-confidence output.
- **OpenAI Bridge** — drop-in OpenAI-compatible API (`POST /v1/chat/completions` on the REST server and the localhost bridge) for third-party tools to call Flexie's LLM chain.
- **Task-based routing** — `CODING`, `VISION`, `RESEARCH`, `CONVERSATION` task types each select the optimal LLM.

### Phase 6 — Desktop & IDE Integration
- **VSCode Extension** (`extension/`) — installs settings, keybindings, and workspace configuration via `templates/react_vite/`.
- **Workspace Launcher** — automatically opens the correct workspace in your IDE when a dev job starts.
- **IDE Integration** (`tests/test_ide_integration.py`) — verifies VSCode launch, settings injection, and extension activation.
- **React/Vite Template** (`templates/react_vite/`) — scaffolds new projects from a production-ready React+Vite template with Flexie pre-wired.

### Phase 7 — E2E Dev Assistant & Verification
- **Autonomous Build Jobs** (`core/jobs/`) — full lifecycle: Plan → Scaffold → Generate → Verify → Launch.
  - `planner.py` — LLM generates `PLAN.md`, `ACCEPTANCE.md`, `AGENTS.md`; template matching + fallback plans.
  - `generator.py` — file-by-file code generation with AST/JSON/tag syntax validation + single-repair attempt.
  - `scaffold.py` — creates directory structure, writes stubs, installs dependencies.
  - `verifier.py` — per-stack env setup (venv/npm), lint → test → start → smoke test; self-heal loop (3 attempts, error-signature dedup).
  - `git_ops.py` — `git init`, per-phase commits, phase `undo` (`git reset --hard HEAD~1`).
  - `manager.py` — singleton `JobManager`, background worker thread, `EventBus` emission, job persistence (`JobStore`).
- **E2E Test** (`tests/test_e2e_dev_assistant.py`) — full pipeline from "build a Flask todo API" to running server smoke-test.
- **Specialist Agents** (`core/specialists.py`) — Dodaios-style multi-agent delegation:
  - `Lead` (Jarvis) — goal decomposition, routing, final synthesis.
  - `Coder` — workspace files, terminal execution, tests, git.
  - `Researcher` — browser navigation, scraping, web search, summarization.
  - `System` — Windows desktop control, window management, volume, app ops.
- **MCP Adapter** (`core/mcp_adapter.py`) — MCP stdio JSON-RPC 2.0 + HTTP client:
  - Spawns any external MCP server as a subprocess.
  - Discovers tools via `tools/list` RPC.
  - Registers discovered tools into Flexie's `ToolRegistry` with permission-level mapping.
  - Manages server lifecycle, reconnects on crash.
- **REST/SSE API** (`interface/api_server.py`, FastAPI `:8768`) — headless external interface:
  - `POST /command` — queue a command (returns `queued`; 429 when the queue is full).
  - `GET /api/flexie/events` — Server-Sent Events: assistant state (active, mode) every 2 s, capped at 8 streams.
  - `POST /page-assist` — ask Flexie about a webpage (title, URL, selected text, page content).
  - `POST /api/flexie/approve` / `/reject` — resolve an approval **by request id** (400 without one, 404 if it is not pending).
  - `GET /health` — liveness probe.
  - Bearer token auth (`utils/udp_auth.py`), Host/Origin checks, no CORS headers except for the extension and `FLEXIE_EXTRA_ORIGINS`.
- **Browser Extension** (`extension/`, Manifest V3):
  - Sidebar panel with voice dictation + command input, wired to `:8768` REST API.
  - Floating "Ask Flexie" pill appears on text selection — explain, rewrite, debug.
  - Right-click context menus on any page, image, or code snippet.
  - Permission approval prompts before sensitive page actions.
- **Vision mode / orb UI** (`vision/`, Next.js + Three.js + MediaPipe) — a hand-gesture 3D orb. Start it by saying "open vision mode" (see *Vision mode* below).
  - Real-time hand tracking — pinch to spin, two hands to zoom; `G` toggles gestures, `R` resets.
  - `JarvisOrb.tsx` tries to open a WebSocket to the bridge at `ws://127.0.0.1:8765` to show assistant state, **but the hardened bridge only accepts its own dashboard origin and requires an `AUTH:<token>` first message, so from `http://localhost:3000` that connection is rejected.** The orb works standalone; the live link to Flexie is not wired (known gap).

---

## Reliability, Safety & Self-Awareness (Nov 2026 hardening)

**Safety model.** Every typed or spoken command passes `FlexieController` first: `SafetyGuard` (blocklist matched on NFKC-normalised text, so zero-width and full-width tricks do not slip through; restricted words match whole words only) and `DangerGate` (risky intent judged per sentence and clause, so "what time is it. delete everything" is caught while "how do I delete a file" is not). A risky command creates an approval request with an id and a TTL (confirmation expires after 60 s). Saying yes approves *that request*; the command then runs inside a one-shot grant that is consumed afterwards, so one "yes" can never authorise a second action. Content from the web, mail, MCP tools or the clipboard marks the current command as untrusted and effectful tools then require confirmation.

**Tool layer.** `ToolRegistry` enforces permission, per-tool timeouts (worker pool; a timed-out non-idempotent call cannot be started twice), argument bounds, and declared capabilities (a tool that needs a capability it did not declare is refused). File tools go through `utils/path_jail.py` (no `.git`, `.env`, source folders or token files; UNC, 8.3 names, junctions and NTFS streams handled). `terminal.run` has a per-binary subcommand/flag policy with no shell. MCP tool names are `mcp__server__tool`, default permission is *confirm*, output is capped and wrapped as untrusted. Plugins are opt-in: only top-level `plugins/<name>.py` files listed (one name per line) in a `plugins/allowed_plugins.txt` that you create — or everything if you set `FLEXIE_ALLOW_PLUGINS=1` — are loaded; there is no `plugins/` folder by default, so nothing loads.

**Memory.** Values are stored JSON-encoded and reload correctly after a restart; search is token overlap weighted by importance, confidence and recency; secrets are scrubbed before storing; conversation entries expire after 14 days and tasks after 30; maintenance prunes hourly. Assistant replies are no longer stored as memories. "Forget" reaches chat history, activity logs, session logs, saved responses, the profile, both wiki copies and the vector store. All SQLite databases share one WAL connection per file with atomic transactions (`utils/sqlite_util.py`).

**LLM layer.** SDK auto-retries are off (`max_retries=0`) with explicit timeouts (Gemini is clamped to at least 15 s because it rejects shorter deadlines); a rate-limited provider falls through to the next one (Groq tries its sibling models first, `GROQ_FALLBACK_MODELS`); the circuit breaker recovers after a cooldown; streaming never repeats text after a mid-stream fallback; failures are recorded in telemetry. Answers cached for 45 s only when real, and never for time-sensitive prompts.

**Self-awareness** (`core/self_model.py`). Questions about Flexie itself are routed by the router to the `awareness` intent and answered from live state:

| Ask | Answered from |
|---|---|
| "what model are you using", "who made you" | configured provider clients and model names (it says it is not GPT-4) |
| "what did you just do", "did that work" | the command log: command, intent, outcome, reply, time |
| "why did that fail" | the recorded error or what Flexie told you (a reply like "I couldn't find…" counts as a failure) |
| "are you listening", "what are you doing" | awake/asleep, busy/idle, uptime, commands handled, available models |
| "what do you remember about me" | saved facts, with junk and questions filtered out |
| "what tools do you have", "what can't you do" | intent count, registered tools, real limits (e.g. no vision model configured) |

The system prompt also tells the model what Flexie is and not to claim actions it was not told happened.

**Screen & vision.** "check my screen", "describe/summarize my screen" capture a screenshot (downscaled to 1280 px) and ask a vision-capable provider (only Gemini today). If no vision model answers, Flexie says so and reads the on-screen text with OCR instead of guessing. "take a screenshot" saves the file and says where.

**Image download** (`engines/image_downloader.py`, `core/handlers/images.py`). "download 5 images of cats" searches (DuckDuckGo images, safe-search on) and saves up to 20 images into `Downloads\Flexie Images\<topic>-<time>\`; "download images from <page URL>" takes `<img>`/`og:image`/linked image files from that page. Only public http(s) addresses (redirects re-checked), at most 15 MB each, must declare an image type *and* decode as an image, duplicates skipped, files get fresh names. It cannot read the tab open in your own Chrome.

**Vision mode** (`engines/vision_mode.py`, `core/handlers/vision_mode.py`). "open/start/launch vision mode" (or "start the orb") runs `npm ci` once if `vision/node_modules` is missing, starts `npm run dev` on the first free port from 3000, waits until it answers and opens it. "close/stop vision mode" kills that process tree; it is also stopped when Flexie exits. Needs Node.js/npm.

**Project builder.** A model failure message ("I've searched for you…") is never written into a source file: the generator retries with a pause, then fails that file clearly (resume later). A file that is empty or comments only is not written. The static-site verifier checks that every linked script/stylesheet exists, is not a stub and contains no failure text, so a job is no longer "done" with an empty `app.js`.

---

## All Voice/Text Commands

**Covered by the 158-case routing eval (`python -m evals.run`, 100%) and `tests/test_router.py`:**

| Category | Example Commands | Intent |
|---|---|---|
| **Social** | `hello`, `hey flexie`, `how are you` | `social` |
| **Voice** | `test voice`, `start dictation` | `voice`/`dictation_mode` |
| **Weather** | `what is the weather`, `weather in chennai` | `weather` |
| **News** | `tell me the news` | `news` |
| **Alarm/Timer** | `set alarm for 7am`, `set timer for 5 minutes`, `what is the time` | `alarm` |
| **Translate** | `translate hello to spanish` | `translate` |
| **Reminders** | `remind me to buy milk`, `list reminders` | `remind_me`/`list_reminders` |
| **Notify** | `notify me at 5pm` | `notification` |
| **Files** | `save file to downloads`, `create folder test`, `organize desktop` | `file_save`/`file_op` |
| **Apps** | `open notepad`, `open chrome` | `app_op` |
| **Browser** | `open website google.com`, `search for cats` | `browser_navigate`/`search` |
| **YouTube** | `play song on youtube`, `next video` | `play_youtube`/`youtube` |
| **Vision** | `analyze screen`, `take screenshot` | `vision_analyze`/`vision_capture` |
| **Local Code** | `search my code for router`, `find function handle_command` | `local_code_search` |
| **Code Gen** | `tell me binary search code and save to downloads`, `generate python code for sorting` | `code_gen` |
| **Research** | `what is photosynthesis and save to downloads`, `research ai` | `research` |
| **Automation** | `schedule check gmail daily at 9am`, `list automations` | `automation` |
| **Gmail** | `check gmail`, `send email to test@gmail.com` | `gmail`/`comm` |
| **Memory** | `remember my name is Dhanush`, `what do you remember` | `memory`/`memory_system` |
| **Awareness / self** | `who are you`, `what model are you using`, `what did you just do`, `why did that fail`, `are you listening`, `what do you remember about me`, `what can't you do` | `awareness` |
| **Vision mode** | `open vision mode`, `start the orb`, `close vision mode` | `vision_mode` |
| **Screen** | `check my screen`, `summarize my screen`, `analyze my screen`, `read my screen` | `vision_analyze` |
| **Images** | `download 5 images of cats`, `download images from <url>` | `image_download` |
| **Chrome** | `open chrome and search for cats`, `close the chrome that you opened` | `app_op` |
| **Dismiss / undo** | `skip that`, `never mind` (instant "Okay."); `wrong`, `undo that` | `conversational` / `undo` |
| **Image** | `generate image of cat`, `draw a picture` | `image_gen` |
| **PDF** | `read pdf`, `summarize pdf` | `pdf` |
| **Clipboard** | `copy this`, `paste it`, `paste the result` | `clipboard_mgr` |
| **Wiki** | `wikipedia python` | `wiki` |
| **Jokes/Quotes** | `tell me a joke`, `give me a quote` | `jokes`/`quotes` |
| **Password/QR** | `generate password`, `generate qr code for google.com` | `password`/`qr_code` |
| **Dictionary** | `define serendipity` | `dictionary` |
| **Facts** | `tell me a fact` | `facts` |
| **Pomodoro** | `start pomodoro` | `pomodoro` |
| **IP** | `what is my ip` | `ip_lookup` |
| **Text Tools** | `count words`, `reverse text` | `text_tools` |
| **Hash** | `hash this text`, `encode base64` | `hash_encoder` |
| **JSON** | `format json` | `json_fmt` |
| **Color/Lorem/UUID** | `random color`, `generate lorem ipsum`, `generate uuid` | `color_info`/`lorem`/`uuid` |
| **Tip/BMI/Age** | `calculate tip for 100`, `calculate bmi`, `how old am i` | `tip_calc`/`body_metrics`/`age_calc` |

**Multi-step planning (new):**
```
open notepad and create binary search code and save to downloads  # 3 steps via DAG, all executed
tell me binary search code and save to downloads  # single code_gen, not split
```

### Complete Feature List (96 Intents, 43 Engines, 49 Handler Modules)

**The 96 trigger-table intents in `core/router.py` (the first 90 are listed; the job-control intents follow the table):**

| # | Intent | Trigger Example | Handler | Category |
|---:|--------|---------|---------------|----------|
| 1 | `undo` | `undo`, `revert` | `handlers/system.py:10` | System |
| 2 | `voice_macro` | `start coding mode` | `handlers/system.py:178` | System |
| 3 | `daily_briefing` | `good morning flexie` | `handlers/dev.py:handle_briefing` | System |
| 4 | `meeting_mode` | `start meeting mode` | `handlers/system.py` | System |
| 5 | `dictation_mode` | `start dictation` | `handlers/system.py` | Voice |
| 6 | `take_note` | `take a note` | `controller.py:147` VectorStore | Memory |
| 7 | `memory_search` | `search memory` | `controller.py:157` | Memory |
| 8 | `exit` | `exit`, `quit` | `handlers/system.py:41` | System |
| 9 | `browser_control` | `click on login` | `handlers/browser.py:13` `engines/browser.py` | Browser |
| 10 | `browser_tabs` | `new tab`, `close tab` | `handlers/browser.py:39` | Browser |
| 11 | `browser_extract` | `summarize page`, `extract links` | `handlers/browser.py:60` | Browser |
| 12 | `play_youtube` | `play song on youtube` | `handlers/media.py:handle_play_youtube` `engines/browser.py` | Media |
| 13 | `gmail` | `check gmail`, `read emails` | `handlers/browser.py:72` `engines/email_engine.py:31` | Communication |
| 14 | `github` | `open github` | `handlers/browser.py` | Dev |
| 15 | `mode` | `change mode to hacker` | `handlers/system.py:26` `Config.MODES` | System |
| 16 | `power` | `shutdown pc`, `lock screen` | `handlers/system.py:50` `engines/system.py` | System |
| 17 | `browser_navigate` | `open website google.com` | `handlers/browser.py:4` | Browser |
| 18 | `youtube` | `next video`, `pause video` | `handlers/media.py` | Media |
| 19 | `browser_search` | `search in chrome` | `handlers/search.py:7` | Browser |
| 20 | `multi_tab_research` | `research latest`, `deep dive` | `handlers/browser.py` DAG | Browser |
| 21 | `remind_me` | `remind me to buy milk` | `handlers/reminders.py` | Productivity |
| 22 | `list_reminders` | `list reminders` | `handlers/reminders.py` | Productivity |
| 23 | `media` | `volume 50`, `brightness 70` | `handlers/system.py:96` | System |
| 24 | `app_op` | `open notepad`, `open chrome` | `handlers/system.py:120` `engines/files.py:60` | System |
| 25 | `vision_analyze` | `analyze screen` | `handlers/vision.py` `engines/vision.py` | Vision |
| 26 | `vision_debug` | `debug screen` | `engines/developer.py:86` | Vision |
| 27 | `vision_read` | `read screen` | `handlers/vision.py` | Vision |
| 28 | `vision_capture` | `take screenshot` | `handlers/vision.py` | Vision |
| 29 | `camera_capture` | `open camera` | `handlers/vision.py` | Vision |
| 30 | `vision_show` | `show screen` | `handlers/vision.py` | Vision |
| 31 | `vision_manage` | `manage vision` | `handlers/vision.py` | Vision |
| 32 | `dev_explain` | `explain project` | `engines/developer.py:108` | Dev |
| 33 | `repo_analyzer` | `analyze repository` | `engines/developer.py:130` | Dev |
| 34 | `project_explainer` | `explain project` | `engines/developer.py:148` | Dev |
| 35 | `bug_hunter` | `audit repository` | `engines/developer.py:156` | Dev |
| 36 | `test_generator` | `generate tests` | `engines/developer.py:177` | Dev |
| 37 | `sdd_build` | `build project` | `engines/developer.py:205` | Dev |
| 38 | `file_rename` | `rename file a to b` | `handlers/files.py:5` | Files |
| 39 | `file_delete` | `delete file test.txt` | `handlers/files.py:10` | Files |
| 40 | `file_save` | `save file to downloads` | `handlers/files.py:19` `handlers/code_gen.py` | Files |
| 41 | `file_op` | `create folder test`, `organize desktop` | `handlers/files.py:24` | Files |
| 42 | `knowledge_search` | `search my files for notes` | `handlers/files.py` `engines/knowledge.py` | Knowledge |
| 43 | `intel` | `what should i do` | `handlers/dev.py:handle_intel` | Intelligence |
| 44 | `briefing` | `daily briefing` | `handlers/dev.py:handle_briefing` | Intelligence |
| 45 | `clipboard` | `analyze clipboard` | `handlers/dev.py:handle_clipboard` | Intelligence |
| 46 | `auto_save` | `start auto save` | `handlers/system.py:153` | System |
| 47 | `save_active` | `save this file` | `handlers/system.py:146` | System |
| 48 | `dev_build` | `build a website` | `engines/developer.py:205` | Dev |
| 49 | `dev` | `run python script` | `engines/developer.py:65` | Dev |
| 50 | `comm` | `send email to test@gmail.com` | `handlers/system.py:163` | Communication |
| 51 | `voice` | `test voice`, `can you hear me` | `handlers/system.py:178` `interface/voice.py` | Voice |
| 52 | `social` | `hello`, `hey flexie` | `handlers/dispatcher.py:76` | Social |
| 53 | `search` | `search for cats` | `handlers/search.py:7` DuckDuckGo | Search |
| 54 | `calc` | `calculate 5 plus 5` | `handlers/tools.py:handle_calc` | Tools |
| 55 | `convert` | `convert 5 km to miles` | `handlers/converter.py` | Tools |
| 56 | `translate` | `translate hello to spanish` | `handlers/tools.py:handle_translate` | Tools |
| 57 | `status` | `check battery`, `cpu status` | `handlers/tools.py:handle_status` | System |
| 58 | `memory` | `remember my name is Dhanush` | `handlers/tools.py:handle_memory` `engines/memory.py` | Memory |
| 59 | `weather` | `weather in chennai` | `handlers/weather.py` `engines/weather.py` | Free Plugin |
| 60 | `image_gen` | `generate image of cat` | `handlers/image_gen.py` `engines/image_gen.py` | Free Plugin |
| 61 | `news` | `tell me the news` | `handlers/news.py` `engines/news.py` | Free Plugin |
| 62 | `alarm` | `set alarm for 7am`, `what is the time` | `handlers/alarm.py` `engines/alarm.py` | Free Plugin |
| 63 | `pdf` | `read pdf`, `summarize pdf` | `handlers/pdf.py` `engines/pdf_reader.py` | Free Plugin |
| 64 | `clipboard_mgr` | `copy this`, `paste it` | `handlers/clipboard_mgr.py` | Free Plugin |
| 65 | `local_code_search` | `search my code for router` | `handlers/code_search.py` `engines/code_search.py` | Dev |
| 66 | `summarize` | `summarize this` | `handlers/summarize.py` | Free Plugin |
| 67 | `awareness` | `who are you` | `handlers/awareness.py` `engines/self_awareness.py` | Intelligence |
| 68 | `memory_system` | `what do you remember` | `handlers/memory_system.py` `engines/memory_system.py` | Memory |
| 69 | `notification` | `notify me at 5pm` | `handlers/notification.py` | Productivity |
| 70 | `wiki` | `wikipedia python` | `handlers/wiki.py` `engines/wiki.py` | Free Plugin |
| 71 | `jokes` | `tell me a joke` | `handlers/jokes.py` | Free Plugin |
| 72 | `quotes` | `give me a quote` | `handlers/quotes.py` | Free Plugin |
| 73 | `password` | `generate password` | `handlers/password.py` | Free Plugin |
| 74 | `qr_code` | `generate qr code for google.com` | `handlers/qrcode.py` | Free Plugin |
| 75 | `dictionary` | `define serendipity` | `handlers/dictionary.py` | Free Plugin |
| 76 | `facts` | `tell me a fact` | `handlers/facts.py` | Free Plugin |
| 77 | `pomodoro` | `start pomodoro` | `handlers/pomodoro.py` | Free Plugin |
| 78 | `ip_lookup` | `what is my ip` | `handlers/ip_lookup.py` | Free Plugin |
| 79 | `text_tools` | `count words`, `reverse text` | `handlers/text_tools.py` | Free Plugin |
| 80 | `hash_encoder` | `hash this text`, `encode base64` | `handlers/hash_encoder.py` | Free Plugin |
| 81 | `json_fmt` | `format json` | `handlers/json_fmt.py` | Free Plugin |
| 82 | `color_info` | `random color` | `handlers/color_info.py` | Free Plugin |
| 83 | `lorem` | `generate lorem ipsum` | `handlers/lorem.py` | Free Plugin |
| 84 | `uuid` | `generate uuid` | `handlers/uuid.py` | Free Plugin |
| 85 | `tip_calc` | `calculate tip for 100` | `handlers/tip.py` | Free Plugin |
| 86 | `body_metrics` | `calculate bmi` | `handlers/body_metrics.py` | Free Plugin |
| 87 | `age_calc` | `how old am i` | `handlers/age.py` | Free Plugin |
| 88 | `code_gen` | `tell me binary search code and save to downloads` | `handlers/code_gen.py` | Dev |
| 89 | `research` | `what is photosynthesis and save to downloads` | `handlers/research.py` | Intelligence |
| 90 | `automation` | `schedule check gmail daily at 9am` | `handlers/automation.py` `engines/automation.py` | Automation |
| 91 | `job_status` | `how is the build going` | `core/jobs/handler.py` | Dev Jobs |
| 92 | `job_pause` | `pause the build` | `core/jobs/handler.py` | Dev Jobs |
| 93 | `job_resume` | `resume the build` | `core/jobs/handler.py` | Dev Jobs |
| 94 | `job_cancel` | `cancel the build` | `core/jobs/handler.py` | Dev Jobs |
| 95 | `job_undo` | `undo last phase` | `core/jobs/handler.py` | Dev Jobs |

**Intents produced only by `NL_OVERRIDES` (regex phrasing rules, 197 of them):** `image_download`, `vision_mode`, `todo_list`, `mail_check/read/send/reply/forward/search/summarize/count/delete/archive/draft/folders/mark_read/sent/compose`, `job_fix`, `job_open`, `build_project`, `open_web_ui`, `run_command`, and `conversational` (for dismissals such as "skip that"). Questions about Flexie itself, "open chrome and search …", screen requests and "vision mode" are matched here first.

**43 engine modules `engines/`:** `age_calc`, `alarm`, `automation`, `body_metrics`, `browser`, `clipboard_mgr`, `code_search`, `color_info`, `developer`, `dictionary`, `email_engine`, `facts`, `files`, `hash_encoder`, `image_downloader`, `image_gen`, `intelligence`, `ip_lookup`, `jokes`, `json_formatter`, `knowledge`, `long_term_memory`, `lorem`, `memory`, `memory_system`, `music`, `news`, `password_gen`, `pdf_reader`, `pomodoro`, `qrcode_gen`, `quotes`, `self_awareness`, `system`, `text_summarizer`, `text_tools`, `tip_calc`, `uuid_gen`, `vision`, `vision_mode`, `weather`, `wiki`, `youtube_controller`.

**49 handler modules `core/handlers/`:** `age`, `agents`, `alarm`, `automation`, `awareness`, `body_metrics`, `browser`, `clipboard_mgr`, `code_gen`, `code_search`, `color_info`, `context`, `converter`, `dev`, `dictionary`, `dispatcher`, `facts`, `files`, `hash_encoder`, `image_gen`, `images`, `ip_lookup`, `jokes`, `json_fmt`, `lorem`, `mail`, `media`, `memory_system`, `news`, `notification`, `password`, `pdf`, `pomodoro`, `qrcode`, `quotes`, `reminders`, `research`, `search`, `summarize`, `system`, `text_tools`, `tip`, `todo`, `tools`, `uuid`, `vision`, `vision_mode`, `weather`, `wiki`.

---

## Engines & Stack

| Engine | Tech | Free? |
|---|---|-------|
| Voice | SpeechRecognition, Vosk, edge-tts (neural) + pygame, SAPI fallback, webrtcvad | Yes |
| LLM | Groq (openai/gpt-oss-20b, then gpt-oss-120b / qwen3 siblings), OpenAI gpt-4o-mini, DeepSeek, Mistral, Gemini (`gemini-flash-latest`), Claude, Ollama, DDGS fallback | Free tiers vary |
| Browser | Playwright 1.52 chromium persistent `browser_session/` | Yes |
| Files | FileManager, PathResolver | Yes |
| Code | CodeSearchEngine, CodeGen, Research (DDG + LLM 618 words) | Yes |
| Weather/News/Wiki | OpenWeather, NewsAPI, Wikipedia | Yes |
| Memory | Chroma PersistentClient, SQLite MemoryManager | Yes |
| Automation | AutomationScheduler (daily/hourly/interval 60s poll) | Yes |
| Vision | VisionEngine: screenshot (pyautogui), Gemini vision, Tesseract OCR fallback; `vision/` orb UI (Next.js, Three.js, MediaPipe) | Yes |
| UI | PyQt6 HUD, web dashboard + WebSocket bridge (HTTP 8766, WS 8765), signed UDP 9886 (Qt UI) / 9888 (web bridge) / 9887 (assistant) | Yes |

---

## What Flexie Can Do

- Open any app/file/folder via fuzzy search `engines/files.py:60` `os.startfile` fallback.
- Browse, fill forms, click via DOM or visual fallback `engines/browser.py:340` Gemini coordinates.
- Generate code (python/java/js/cpp) and save to `Downloads/X.py` `handlers/code_gen.py:44`.
- Research online (photosynthesis 618 words) and save `handlers/research.py:44`.
- Schedule automations `engines/automation.py:12` built-in daily briefing + auto organize.
- Remember preferences `core/memory_manager.py:31` 6 categories, auto-extract.
- Self-correct via `workflow_executor.py:82` verify + `GoalEvaluator` retry.
- Stream LLM response sentence-by-sentence `core/brain.py:157` `ask_stream`.
- Handle `paste it`/`copy it` via `router.py:86` `clipboard_mgr`.
- Voice VAD 150 threshold `voice.py:12` webrtcvad boost `voice.py:310` 1.5/80, 8s watchdog.

---

## What Flexie Cannot Do

- Not true AGI - narrow, no self-improvement beyond `adaptive_router.py:21`.
- No cloud sync - local SQLite/Chroma only.
- Windows only - `pycaw`, `comtypes`, `start` shell.
- No mobile app - `flexie_web/` is PWA-ready but not packaged.
- Requires internet for Groq/Gemini - falls back to Ollama/DDG, Vosk offline limited.
- No fine-tuned model - uses base LLMs.

---

## Autonomous Dev Assistant

Flexie can build entire projects autonomously — just describe what you want:

```
build me a Flask todo REST API with SQLite
create a React dashboard that shows weather data
scaffold a Node.js CLI tool for file compression
```

**5-Phase Build Pipeline** (`core/jobs/`):

| Phase | What happens |
|---|---|
| **1. Plan** | LLM generates `PLAN.md` (stack, files, deps), `ACCEPTANCE.md` (criteria), `AGENTS.md` (role assignments) |
| **2. Scaffold** | Creates directory structure, writes stub files, commits phase to git |
| **3. Generate** | File-by-file LLM code generation with AST/JSON/HTML syntax validation; single-repair attempt on syntax fail |
| **4. Verify** | Stack detection (Python/Node/Rust/Java/Static), env setup (venv/npm), lint → tests → start → smoke-test |
| **5. Self-heal** | Up to 3 repair attempts; error-signature deduplication prevents infinite loops on same error |

**Git versioning** — every phase is committed; `undo last phase` rolls back via `git reset --hard HEAD~1`.

**Security** — path jail enforcement, secret neutralization (OPENAI/GROQ/GITHUB/AWS keys scrubbed), `.env.example` auto-generated.

**Resource caps** — max 60 files per project (`FLEXIE_JOB_MAX_FILES`), max 300 KB per file, token budget per job (`FLEXIE_JOB_TOKEN_BUDGET`, default 50,000), hard caps on subprocesses.

**Where projects go** — each job gets its own folder `<slug>-<id>` under `Config.CODE_OUTPUT_DIR` (default `Downloads`, override with `FLEXIE_CODE_OUTPUT_DIR`), with its own git repo (git is never initialised inside a parent repo). A job that fails or is cancelled before producing any file removes its empty folder.

**Model failures** — if the model is rate-limited or down, the generator retries (pauses 3 s, then 8 s) and then fails that file with a clear message; the fallback text of the brain is never written into a file. Resume the job later to continue.

**Verification** — for static sites the verifier checks that `index.html` links to scripts/stylesheets that exist, are not stubs and are not error text; the test phase for stacks without tests says so instead of claiming success.

---

## Specialist Agents

Flexie delegates complex tasks to purpose-built agents (`core/specialists.py`):

| Agent | Role | Authorized Tools |
|---|---|---|
| **Lead (Jarvis)** | Goal decomposition, routing, final synthesis | All tools (orchestrator) |
| **Coder** | Code generation, file writes, terminal, tests, git | `code_gen`, `terminal`, `file_*`, `git_*` |
| **Researcher** | Web search, browser navigation, scraping, summarization | `browser_*`, `search`, `wiki`, `research` |
| **System** | Desktop control, window snap, volume, app ops | `app_op`, `desktop_*`, `media`, `vision_*` |

Each specialist has a **scoped tool list** — the LLM can only call tools in its role. Specialists run their own observe→act→verify loop before returning results to the Lead agent.

---

## MCP Integration

Flexie connects to any external MCP (Model Context Protocol) server via `core/mcp_adapter.py`:

```python
# .flexie_mcp.json — define external MCP servers
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"],
      "enabled": true
    },
    {
      "name": "github",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "ghp_..."}
    }
  ]
}
```

- **Auto-discovery** — calls `tools/list` RPC on startup; registers each tool into `ToolRegistry`.
- **Permission mapping** — read tools → `READ_ONLY`; write/exec tools → `SAFE_ACTION` or `USER_CONFIRMATION`.
- **Lifecycle management** — spawns server subprocess, heartbeats, reconnects on crash.
- **Protocol** — JSON-RPC 2.0 over stdio; HTTP transport also supported.

---

## Browser Extension

Install the Chrome/Edge extension (`extension/`) to get Flexie in every webpage:

**Capabilities:**
- **Sidebar panel** — voice dictation + text input, full command interface, connects to Flexie REST API at `http://127.0.0.1:8768`.
- **Floating pill** — appears on any text selection; click to explain, rewrite, translate, or debug with Flexie.
- **Context menus** — right-click on any page, image, link, or code block → "Ask Flexie About This".
- **Page assist** — sends current page URL, title, and selected text to `/page-assist` endpoint for contextual answers.
- **Permission prompts** — shows interactive approval dialog before any sensitive action (form fill, click, navigation).

**Installation:**
```
1. chrome://extensions/ → Developer mode ON
2. Load unpacked → select flexie_v2/extension/
3. Pin Flexie icon → Open Sidebar
```

---

## REST & SSE API

`interface/api_server.py` — FastAPI service at `http://127.0.0.1:8768` (started by `main.py`; the port is checked first and a bind failure is logged as an error). Every endpoint also exists under `/api/jarvis/*` for older clients.

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness probe (no auth) |
| `/command`, `/api/flexie/commands` | POST | Queue a command (`{"command": "..."}`, max length enforced; 429 when the queue is full) |
| `/api/flexie/status` | GET | Mode, awake state, active provider/model, job status |
| `/api/flexie/usage` | GET | Token / cost / latency totals and recent commands (from telemetry) |
| `/api/flexie/jobs` | GET | Build jobs |
| `/api/flexie/events` | GET | SSE: assistant state (`active`, `mode`) every 2 s; at most 8 concurrent streams |
| `/page-assist`, `/api/flexie/page-assistant` | POST | Ask about a page (url, title, content, selected text; size-limited) |
| `/api/flexie/approve`, `/api/flexie/reject` | POST | Resolve an approval by `request_id` |
| `/v1/chat/completions` | POST | OpenAI-compatible endpoint backed by Flexie's LLM chain |
| `/api/flexie/mail/*` | GET/POST | inbox, all, count, sent, folders, search, send, reply, compose-ai, summarize, delete, archive, mark-read, draft, move |

**Auth:** `Authorization: Bearer <token>` — the per-run token, also written to `.flexie_udp_token`. Host must be `localhost`/`127.0.0.1` on the right port; browser origins are limited to the extension (`FLEXIE_EXTENSION_IDS`) and `FLEXIE_EXTRA_ORIGINS`. **Mail send/reply block until you approve** them through `/approve` (wait set by `FLEXIE_MAIL_APPROVAL_WAIT`, default 60 s; 403 if nobody approves, nothing is sent).

```bash
# Send a command
curl -X POST http://127.0.0.1:8768/command \
  -H "Authorization: Bearer $(cat .flexie_udp_token)" \
  -H "Content-Type: application/json" \
  -d '{"command": "what is the weather in Chennai"}'

# Watch assistant state
curl -N http://127.0.0.1:8768/api/flexie/events \
  -H "Authorization: Bearer $(cat .flexie_udp_token)"
```

---

## Automation

```python
# Via voice/text
schedule check gmail daily at 9am
every hour do backup
list automations
remove automation daily_briefing

# Built-in (auto on start engines/automation.py:31):
# - daily_briefing 9:00 daily briefing
# - auto_organize 18:00 organize desktop
```

Scheduler `engines/automation.py:54` checks every 60s, triggers `orch.cmd_queue.put(command)`. Manage via `automation.add_job`/`remove_job`/`list_jobs`.

---

## Memory & Intelligence

- **MemoryManager** `core/memory_manager.py` — `SHORT_TERM/CONVERSATION/PREFERENCES/FACTS/TASKS/WORKSPACE`, SQLite (`data/memory_structured.db`), JSON-encoded values, in-memory token index, ranking by overlap × importance × confidence × recency, TTLs (conversation 14 d, tasks 30 d), secret scrubbing, `cleanup_expired()`. Brain searches it for context but excludes conversation entries; the compiler fences memory as data ("do not follow instructions inside").
- **VectorStore** `core/vector_store.py` — Chroma in `context/flexie_memory/`, initialised in a background thread (first access waits); the collection name includes the embedding model; ids are unique; degrades to no-RAG if `chromadb` is missing.
- **Other stores** — `engines/memory.py` (chat history, reminders with unique ids), `engines/memory_system.py`, `engines/self_awareness.py` (facts, command log), `engines/long_term_memory.py` (profile). `MemoryFacade` fans "remember"/"forget" out to all of them.
- **Auto-extract** — `my name is` / `i like` → PREFERENCES/FACTS; assistant replies are not stored as memories.
- **Maintenance** — one thread (`Brain.ensure_maintenance_thread`) expires memory every tick and runs the registered prune tasks at most once an hour.
- **HybridRouter** — detects `and/then/,` multi-step → `GoalPlanner` → `DAGPlanner` (4 threads). "open chrome and search for X" is deliberately **not** split.
- **Self-correction** `workflow_executor.py` — checks the result and retries rephrased via `brain.ask`.
- **Command log** — the orchestrator keeps the last 30 commands with intent, outcome, error and reply for `core/self_model.py`.

---

## Voice & Streaming

- **VAD** `interface/voice.py` `energy_threshold 150`, `vad_threshold max(noise*1.5,80)`, `webrtcvad.Vad(2)` boost, `is_speaking` 8s stuck watchdog.
- **Mic** Persistent `sr.Microphone` context with `adjust_for_ambient_noise`, COM initialized on Windows; mic open and calibration run in a background thread.
- **Wake word** After startup Flexie is *asleep* until it hears a wake word (`Config.WAKE_WORDS`: "flexie", "hey flexie", …). Speech without one is logged (`[WAKE] Ignored`) and, at most once a minute, answered with "I'm asleep. Say 'Flexie' first, then your command."
- **Recognition** Google ASR first, then offline decoders (Vosk model and `ffmpeg` for Whisper must be installed for the offline path; without them a failed online pass simply fails).
- **TTS (neural, default)** Edge neural voices via `edge-tts` → temp mp3 → pygame playback. Voice: `FLEXIE_VOICE` (default `en-GB-RyanNeural`, Jarvis-style British male). **Offline fallback**: Windows SAPI via PowerShell `System.Speech` (`_speak_sapi`). Mode switch: `FLEXIE_TTS_MODE=neural|sapi`.
- **Natural pacing** `prepare_speech_text()` strips markdown/emojis/symbols from spoken text (`&`→"and", `%`→"percent", bullets→pauses); `speak()` batches ~2 sentences per clip to avoid choppy per-sentence playback.
- **TTS guard** long replies (>300 chars) truncate at the last **sentence boundary** with "I've posted the full text to your screen." — never mid-word.
- **Streaming** `brain.ask_stream(stream=True)` yields chunks, `orchestrator.speak_stream` splits `(?<=[.!?])` sends `STREAM` UDP `9886` → `web_ui_bridge` WS `8765`.

---

## Safety & Permissions

- **SafetyGuard** `core/safety.py` — blocklist matched on NFKC-normalised text with format characters removed (so `r​m -rf /` and full-width tricks are caught): recursive deletes, `Remove-Item` in all flag orders, `format`/`diskpart`, `shutdown /s`, `iex`, encoded PowerShell, `curl | sh`, DB `DROP`/`DELETE FROM`, system-path writes. Restricted words match whole words only (no more "Essex"). Shell metacharacters in spoken queries are stripped; `$(…)` and backticks are rejected.
- **DangerGate** `core/danger_gate.py` — judges each sentence and clause on its own (`plan_text.split_clauses`); purely informational clauses ("how do I delete…") and reminders are not flagged; sends, payments, deletes, publishes, "get rid of", "factory reset", "clear memory" are. Approvals are short and pure ("yes", "go ahead", "do it"); "ok but first delete everything" is not an approval.
- **PermissionSystem** `core/permission_system.py` — levels `READ_ONLY → SAFE_ACTION → USER_CONFIRMATION → SENSITIVE → DANGEROUS`. `create_approval_request()` returns an id (TTL 120 s here, 60 s in the controller); `approve_request()` activates a grant of 60 s for that request only (`grant_scope`, thread/context-local), consumed after use. An approval never raises the standing level. Untrusted-content taint is tracked per command id.
- **Tools** `core/tool_registry.py` — permission gate, per-tool timeouts, thread-affine tool tags, `idempotent` flag (only `idempotent=True` calls are ever retried), argument schema with bounds. `core/capabilities.py` — undeclared capabilities are refused. `terminal.run` — per-binary subcommand/flag policy, no shell, global deadline; `python.exec` — Docker sandbox with CPU/memory/pid limits, read-only filesystem, no network by default, timeout 1–120 s. Desktop-control actions pass the same gate; Win-key combos, Enter, Alt+F4 need confirmation.
- **File jail** `utils/path_jail.py` — writes denied under `.git`, `.github`, source folders and for `.env*`, keys, tokens, `pyproject.toml`; secret files cannot be read; UNC/other-drive/`..`/junction/8.3/NTFS-stream paths rejected.
- **Mail** — send/reply read back "To X, subject Y — send it?" and need voice confirmation; addresses are validated (single address, no header injection); the REST send/reply endpoints block until approved. IMAP deletes use UIDs and copy-then-delete.
- **Web bridge / API / UDP** `interface/web_ui_bridge.py`, `interface/api_server.py`, `utils/udp_auth.py` — per-run token, Host and Origin checks (DNS-rebinding defence), no wildcard CORS, token given only to the dashboard origin, signed UDP datagrams (`FLEXIE_ALLOW_UNSIGNED_UI=1` only as a migration aid), bounded request sizes and queues. The extension validates endpoints against an allow-list and checks `sender.id`.
- **Privacy** — clipboard history is opt-in (`FLEXIE_CLIPBOARD_MONITOR=1`) and never stores OTP/card/secret-like text; typed form values are never logged or spoken; telemetry and traces redact secrets and prune after 30 days (`FLEXIE_RETENTION_DAYS`).
- **Image/network fetches** — `engines/image_downloader.py` resolves every host and refuses loopback, private, link-local and reserved addresses (including after redirects).
- **Log rotation** `RotatingFileHandler 5MB×3`.
- **Validation** `utils/config.py` `_validate_env()` warns if `GROQ_API_KEY` is missing/invalid. `.env` loading does not override real environment variables.

---

## Getting Started

```bash
# 1. Python 3.10+
python -m venv venv
venv\Scripts\activate

# 2. Install deps (auto on first run via utils/installer.py:29)
pip install -r requirements.txt
# Optional: pip install chromadb webrtcvad docker
# REST API deps (fastapi, uvicorn, httpx) are already in requirements.txt

# 3. Playwright
python -m playwright install chromium

# 4. Env
cp .env.example .env
# Edit .env:
# GROQ_API_KEY=gsk_... (from console.groq.com)
# GEMINI_API_KEY=... (optional, the only vision-capable provider today; GEMINI_MODEL defaults to gemini-flash-latest)
# FLEXIE_EMAIL=... FLEXIE_PASS=... (Gmail app password)
# OPENAI_API_KEY=... (optional, fallback)

# 5. Run core assistant
python main.py  # starts orchestrator + PyQt HUD

# Or run web bridge only
python interface/web_ui_bridge.py  # ws://localhost:8765

# Or run REST/SSE API (for browser extension + external apps)
python interface/api_server.py  # http://localhost:8768

# 5b. Vision mode (optional): needs Node.js + npm. Say "open vision mode";
#     the first run does `npm ci` inside vision/ (a few minutes), then opens http://localhost:3000

# 6. Browser Extension (optional)
#    chrome://extensions/ → Developer mode → Load unpacked → select extension/

# 7. MCP servers (optional — add to .flexie_mcp.json)
#    npm i -g @modelcontextprotocol/server-filesystem
```

---

## Configuration

`utils/config.py` loads `.env` (without overriding variables already set in the environment):

| Var | Default | Purpose |
|---|---|---------|
| `GROQ_API_KEY` | `""` | Groq `openai/gpt-oss-20b` (primary) |
| `GROQ_FALLBACK_MODELS` | `openai/gpt-oss-120b,qwen/qwen3.8-27b` | Tried in order when the main Groq model is rate-limited (limits are per model) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `""` / `gemini-flash-latest` | Gemini (vision + chat fallback). A retired model name falls back to `gemini-flash-latest` then `gemini-3.8-flash` |
| `OPENAI_API_KEY` etc. | `""` | OpenAI / DeepSeek / Mistral / Anthropic keys (each optional) |
| `FLEXIE_LLM_REQUEST_TIMEOUT` | `7` s | Per-request provider timeout (Gemini is raised to ≥ 15 s) |
| `FLEXIE_LOCAL_FIRST` | `1` | Try local Ollama before cloud providers |
| `FLEXIE_ENGINE` | `auto` | Preferred inference engine (`auto`, `ollama`, `brain`) |
| `OLLAMA_URL` | `http://localhost:11434` | Local engine (probe times out after 0.8 s) |
| `FLEXIE_VOICE` / `FLEXIE_TTS_MODE` | `en-GB-RyanNeural` / `neural` | Edge neural voice, or `sapi` for offline |
| `FLEXIE_MIC_DEVICE` | auto | Microphone device |
| `FLEXIE_EMAIL` / `FLEXIE_PASS` | `""` | EmailEngine IMAP/SMTP (cached connection) |
| `FLEXIE_DATA_DIR` | project root | Where databases and runtime files live |
| `FLEXIE_CODE_OUTPUT_DIR` | `~/Downloads` | Where build-job project folders are created |
| `FLEXIE_JOB_MAX_FILES` / `FLEXIE_JOB_MAX_FILE_SIZE_KB` / `FLEXIE_JOB_TOKEN_BUDGET` | `60` / `300` / `50000` | Build-job limits |
| `FLEXIE_RETENTION_DAYS` | `30` | Telemetry and trace retention |
| `FLEXIE_CLIPBOARD_MONITOR` | off | Opt in to clipboard history |
| `FLEXIE_ALLOW_UNSIGNED_UI` | off | Accept unsigned UI datagrams (migration aid) |
| `FLEXIE_EXTRA_ORIGINS` / `FLEXIE_EXTENSION_IDS` | `""` | Extra browser origins / extension ids allowed by the REST API |
| `FLEXIE_MAIL_APPROVAL_WAIT` | `60` s | How long mail send/reply wait for approval |
| `FLEXIE_ALLOW_PLUGINS` | off | Load all top-level plugins (otherwise only names listed in a `plugins/allowed_plugins.txt` you create) |
| `FLEXIE_OPENAI_BRIDGE_ENABLED` / `_PORT` | | OpenAI-compatible bridge |
| `FLEXIE_PRICING_FILE` | built-in | Model price table for cost telemetry |
| `Config.KNOWLEDGE_ROOTS` | Documents/Desktop/Downloads | Folders the knowledge index scans |
| `MCP_CONFIG` | `.flexie_mcp.json` | External MCP server definitions (add `readOnlyTools` to let a server's tools run without confirmation) |

---

## Project Structure

```
flexie_v2/
├── main.py                      installer check → orchestrator → controller wrap → run
├── core/
│   ├── controller.py            safety front door (SafetyGuard, DangerGate, approvals)
│   ├── orchestrator.py          threads, command log, self model, handle_command, run
│   ├── router.py                TYPO_MAP, NL_OVERRIDES (197), triggers (96 intents)
│   ├── hybrid_router.py / model_hub.py / adaptive_router.py
│   ├── brain.py                 provider chain, cache, circuit breaker, streaming, maintenance
│   ├── llm_providers.py / llm_failure.py / inference/ (Ollama etc.)
│   ├── self_model.py            live self-awareness answers + CommandLog
│   ├── permission_system.py / danger_gate.py / safety.py / plan_text.py
│   ├── tool_registry.py / capabilities.py / capability_*.py / run_budget.py
│   ├── coding_tools.py / browser_and_comm_tools.py / desktop_control.py
│   ├── agent_executor.py / goal_planner.py / dag_planner.py / workflow_*.py
│   ├── specialists.py / mcp_adapter.py / skills/ / persona.py
│   ├── memory_manager.py / memory_facade.py / vector_store.py / context_memory.py
│   ├── telemetry/ / traces/ / event_bus/
│   ├── handlers/                49 modules (dispatcher.py chooses by intent)
│   └── jobs/                    planner, generator, scaffold, verifier, git_ops, manager, store, models, process, safe_paths
├── engines/                     43 modules: system, files, browser, email_engine, vision, vision_mode,
│                                image_downloader, memory*, knowledge, automation, music, weather, … (see list above)
├── interface/                   voice.py, ui.py (PyQt6), web_ui_bridge.py + web_ui.html, api_server.py
├── extension/                   Chrome/Edge Manifest V3 (background.js, sidebar, content.js, popup)
├── vision/                      Next.js orb UI (hand tracking), started by "open vision mode"
├── flexie_web/                  web client scaffold
├── context/                     compiler.py (memory → prompt), Chroma data
├── agents/ sandbox/ skills/ templates/   specialist agents, Docker executor, skill files, project templates (plugins/ is created by you, opt-in)
├── evals/                       run.py (routing), agent_run.py (agent), bench.py, tasks/*.jsonl
├── utils/                       config, paths, lazy, path_jail, name_index, sqlite_util, udp_auth, installer, preflight, voice_parse, helpers
├── recovery/analyzer.py         failure diagnosis for workflow steps (shared instance)
├── verification/                step validators (capability / semantic / strict) used by WorkflowExecutor.verify_step
├── tests/                       70 files, 2,054 tests (conftest.py isolates build output)
├── data/                        runtime: telemetry.db, traces.db, memory_structured.db, persona/ (git-ignored where personal)
├── workspace/                   job state (git-ignored)
└── .github/workflows/ci.yml     ruff + pytest (coverage floor) + routing and agent eval gates
```

---

## Testing

```bash
# Full suite (about 4 minutes on Windows: the slowest tests spawn real git/npm processes)
python -m pytest tests -p no:warnings
# 2054 passed, 1 skipped (70 test files)

# Lint (CI blocks on it)
python -m ruff check .

# Routing eval (158 commands; default gate 0.9, an empty task file fails)
python -m evals.run

# Agent eval (59 deterministic cases: budgets, permissions, planning, specialists, taint, usage, wording)
python -m evals.agent_run

# Deterministic benchmark (no model, no network) -> evals/results/bench-*.json/.md
python -m evals.bench
```

Set `GIT_CEILING_DIRECTORIES` to the repo's parent when running tests so git-based tests can never touch a parent repository.

**Suites added during hardening** (each `test_fix_*.py` targets one area):

| Suite | What it covers |
|---|---|
| `test_fix_safety.py`, `test_danger_gate.py`, `test_permission_*` | approvals, clause-level danger detection, normalised blocklist, expiry |
| `test_fix_tools.py`, `test_mcp_adapter.py`, `test_capabilities.py` | path jail, terminal policy, MCP trust, capability policy, retries |
| `test_fix_memory.py`, `test_fix_leftovers_core.py` | transactions, forget, TTL, reminders, prune, background maintenance |
| `test_fix_llm.py` | cache, fallbacks, circuit breaker, telemetry, traces |
| `test_fix_interfaces.py` | bridge/API auth, extension validation, TTS injection, UDP signing |
| `test_fix_heavy.py` | files, email, system, browser, scheduler, knowledge, clipboard |
| `test_fix_utilities.py` | every small handler (hash, JSON, reminders, alarms, converter, …) |
| `test_fix_router.py`, `test_fix_chrome_commands.py` | routing regressions, chrome/close/search, vision mode, dismissals |
| `test_fix_screen_and_text_cmds.py`, `test_fix_projects_and_images.py` | screen commands, build-job failure handling, image downloader, self model |
| `test_speed_startup.py` | heavy libraries are not imported at startup; lazy modules; background init |
| `test_fix_recovery.py`, `test_fix_leftovers_tools.py` | recovery analyzer, mail approval, capability declarations |

These tests use fakes: they do not exercise live models, voice, the extension, a real IMAP server, Docker or MCP servers.

---

## Roadmap

**Phase 2 Intelligence ✓** - Memory 5+5, HybridRouter+GoalPlanner, self-correction
**Phase 3 Autonomy ✓** - AutomationScheduler daily/hourly, DesktopControl+AgentExecutor, async browser DAG, webrtcvad
**Phase 4 Experience ✓** - Streaming ask_stream+speak_stream, web dashboard WORKFLOW/STREAM, safety audit
**Phase 5 Model Hub ✓** - Task-based LLM routing, cheap-first cascade, OpenAI bridge
**Phase 6 IDE Integration ✓** - VSCode extension, workspace launcher, React/Vite scaffold template
**Phase 7 Dev Assistant ✓** - 5-phase build jobs, specialist agents, MCP adapter, REST/SSE API, browser extension, orb UI
**Phase 8 Hardening ✓** (Nov 2026) - safety/approval redesign, tool jail and capability policy, memory transactions and forgetting, LLM fallbacks and telemetry, interface auth, engine fixes, lazy startup (14.5 s → 1.9 s), self-awareness, image download, vision mode, build-job failure handling

**Next (Phase 8+):**
- Plugin marketplace `capability_registry.py:23` — publish/install community tools
- Mobile PWA `flexie_web/` — React PWA packaged for Android/iOS
- Wire the orb UI (`vision/`) to the hardened WebSocket bridge (needs an allowed origin and the token) so it shows live assistant state
- Provider hedging (start a second provider if the first is slow) and a dedicated small routing model
- Remove the unused LangGraph loop (`core/agent_loop.py`)
- Vision always-on — continuous screen monitoring
- Docker strict sandbox `sandbox/executor.py` — full isolation for untrusted code
- Multi-user — shared memory namespaces, per-user permission profiles
- Voice wakeword — always-on "Hey Flexie" detection without VAD polling

---

## Limitations

- Windows 10/11 only (`pycaw`, `comtypes`, `os.startfile`) — Linux/Mac not supported yet.
- Needs mic permission; `pyaudio` optional but `SpeechRecognition` needs it.
- Groq free-tier rate limits — Flexie tries Groq's sibling models, then the next provider; if every provider fails it says so (it does not invent an answer).
- Only Gemini can look at images. If Gemini is overloaded or the key is missing, "describe my screen" falls back to reading the text on screen (needs Tesseract).
- The orb UI in `vision/` is started and stopped by Flexie but is not connected to its live state (see Roadmap).
- Speech recognition depends on Google ASR; without Vosk/ffmpeg there is no offline fallback, and misheard commands are a known weak point.
- The first command after launch can wait a few seconds while the vector store and model clients finish starting in the background.
- Nothing in this repository has been tested against live voice input, a real model session, the browser extension, a real IMAP server, Docker or MCP servers in an automated way; those paths are covered by fakes only.
- Vosk model `~/.cache/vosk/vosk-model-small-en-us-0.15` needed for offline STT.
- Playwright `browser_session/` persistent cookies stored on disk.
- VectorStore degrades to `[]` if `chromadb` not installed (`core/vector_store.py:44`).
- `flexie_activity.log` rotated (5MB×3) but can be verbose under heavy workloads.
- MCP servers must be installed separately (e.g. `npm i -g @modelcontextprotocol/server-filesystem`).
- Browser extension requires Developer Mode in Chrome/Edge — not published to web store.
- REST API (`api_server.py`) requires `fastapi` and `uvicorn`, which are listed under "REST API" in `requirements.txt`.
- Dev jobs workspace (`workspace/`) can grow large; no automatic cleanup.
- Captcha detection pauses browser automation — manual intervention required.

---

## License

MIT — see [LICENSE](LICENSE).

All listed dependencies are permissively licensed and MIT-compatible. PDF
reading uses `pypdf` (BSD-3-Clause); the previous AGPL `pymupdf` dependency was
removed so that distributing binaries carries no copyleft obligation.

---

*Flexie 2.0 — Built for Dhanush. 2,054 tests. Voice → Controller (safety) → Router → Hybrid → ModelHub → Planner → DAG → Specialist → Jobs → MCP → Verify → Memory → Stream → API → Extension → Self-model.*

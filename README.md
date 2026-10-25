# Flexie 2.0 — Autonomous Agentic AI Desktop Assistant

> **Resume:** *Flexie 2.0 — Agentic AI Desktop Assistant — A Windows-native AI agent capable of voice interaction, multi-step task planning, tool execution, desktop automation, memory, web research, code generation, specialist agents, MCP integration, and task verification.*
> **GitHub:** *Flexie 2.0 — Autonomous Agentic AI Desktop Assistant — AI Agent is the core identity; voice, chatbot, automation, browser extension, dev assistant, and desktop control are capabilities of the agent.*

A **zero-config, Windows-native autonomous AI agent** with 30+ free plugins, self-awareness, persistent memory, hybrid agentic routing, browser automation, MCP server integration, specialist multi-agent delegation, REST/SSE API, browser extension, and autonomous dev-assistant build jobs — all running locally on Windows.

**LLM Chain:** Groq → OpenAI → DeepSeek → Mistral → Gemini → Anthropic → Ollama (offline) → DuckDuckGo fallback. Streaming, VAD, desktop control, self-correction, and cheap-first cascade routing included.

**Voice:** Edge neural TTS (Jarvis-style, `en-GB-RyanNeural` default) with offline SAPI fallback, natural sentence-batched speech, and markdown/emoji-free spoken prose.

---

## Table of Contents
- [What Flexie Is](#what-flexie-is)
- [Architecture Overview](#architecture-overview)
- [Core Features](#core-features)
- [New in Phases 5–7](#new-in-phases-57)
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

---

## What Flexie Is

Flexie is a **desktop-native autonomous AI agent** — *AI Agent is the core identity; voice, chatbot, automation, browser extension, dev assistant, and desktop control are capabilities of the agent.*

It listens to voice (VAD) or keyboard (PyQt6 HUD), understands natural language, **plans multi-step tasks** (`GoalPlanner` + `DAGPlanner`), **executes tools** (`ToolRegistry` 30+ tools, `DesktopControl`, `BrowserEngine`), **remembers** (VectorStore + MemoryManager), **delegates to specialist agents** (Coder, Researcher, System), **connects to any MCP server**, and **verifies** (`GoalEvaluator` + self-correction) — not just chat.

**Resume title:** *Flexie 2.0 — Agentic AI Desktop Assistant* — A Windows-native AI agent capable of voice interaction, multi-step task planning, autonomous build jobs, MCP integration, specialist delegation, browser extension, REST API, IDE integration, and task verification.

**GitHub title:** *Flexie 2.0 — Autonomous Agentic AI Desktop Assistant*

**Not a cloud SaaS** — data stays on your machine. External calls only to free LLM APIs (Groq, Gemini) and free public APIs (weather, news, Wikipedia).

**35+ test files, 600+ test cases** — CI runs pytest (blocking) + ruff on every push via `.github/workflows/ci.yml`.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ USER INPUT: Voice (VAD RMS+webrtcvad) / Keyboard / REST API    │
│             Browser Extension / WebSocket / SSE                 │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ INTENT ROUTER (core/router.py)                                  │
│  TYPO_MAP (difflib 0.85) + NL_OVERRIDES (40+ regex) + Triggers  │
│  → Intent + Confidence (0.0-1.0)                                │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ HYBRID ROUTER + MODEL HUB (core/hybrid_router.py)              │
│  Simple (<50ms) → Deterministic                                 │
│  Complex (and/then, len>8, conf<0.7) → GoalPlanner             │
│  Cheap-first cascade routing + task-based LLM selection         │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ ORCHESTRATOR (core/orchestrator.py)                             │
│  TaskClassifier → WorkflowParser → DAGPlanner (4 threads)      │
│  → WorkflowExecutor → AgentExecutor (observe-act-verify)        │
│  → SpecialistDelegation (Lead/Coder/Researcher/System)          │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ HANDLERS → ENGINES → DESKTOP/BROWSER/VISION                     │
│  30+ handlers, 40+ engines, DesktopControl, BrowserEngine       │
│  MCP Tools (external stdio/HTTP servers), Browser+Comm Tools    │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ JOBS SYSTEM (core/jobs/)                                        │
│  Planner → Generator (syntax-validated) → Scaffold → Verifier  │
│  Self-heal (3 attempts) → Git versioning → Phase undo          │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│ MEMORY + BRAIN (core/brain.py)                                  │
│  VectorStore Chroma (5) + MemoryManager (5) → ContextCompiler  │
│  Streaming (Groq stream=True) → speak_stream                    │
│  REST/SSE API (FastAPI :8768) + WebSocket (:8765)              │
└─────────────────────────────────────────────────────────────────┘
```

**Key modules:**
- `core/router.py` - TYPO_MAP, NL_OVERRIDES, compiled triggers, route()
- `core/hybrid_router.py` - ALWAYS_SIMPLE, COMPLEX_PATTERNS, classify()
- `core/goal_planner.py` - TaskGraph decomposition
- `core/dag_planner.py` - ThreadPoolExecutor 4, blocking_execute
- `core/workflow_executor.py` - sequential + verify_step + GoalEvaluator retry
- `core/memory_manager.py` - 6 categories, SQLite, search
- `core/brain.py` - Groq→OpenAI→DeepSeek→Mistral→Gemini→Anthropic→Ollama→DDG, ask_stream
- `core/mcp_adapter.py` - MCP stdio/HTTP client, tool registration into ToolRegistry
- `core/specialists.py` - Lead/Coder/Researcher/System multi-agent delegation
- `core/jobs/` - planner, generator, verifier, git_ops, manager, scaffold
- `interface/api_server.py` - FastAPI REST + SSE endpoints at :8768
- `extension/` - Chrome/Edge Manifest V3 browser extension
- `interface/voice.py` - RMS VAD + webrtcvad, energy 150, threshold 80

---

## Core Features

| Area | Features |
|---|---|
| **Voice** | VAD RMS+webrtcvad, barge-in, Indian English en-IN, Edge neural TTS + SAPI fallback, sentence-batched speech, streaming, 8s stuck watchdog |
| **Browser** | Playwright persistent context, navigate/click/fill/scroll, multi-tab research parallel (DAG), gmail_read, ad skip |
| **Files** | create/rename/delete, organize desktop, Downloads/Desktop/Documents resolver `utils/path_resolver.py` |
| **Code** | Local search `engines/code_search.py`, generation `handlers/code_gen.py` (python/java/js etc) → `Downloads/binary_search.py` |
| **Research** | Web search DDG + LLM 300+ words summary `handlers/research.py` → save to file |
| **Automation** | `engines/automation.py` daily/hourly/interval, built-in daily briefing 9am + auto organize 6pm |
| **Memory** | VectorStore 5 + MemoryManager 5, auto-extract `my name is`/`i like` → PREFERENCES/FACTS |
| **Safety** | SafetyGuard (sanitize-don't-reject + destructive-pattern blocklist), DangerGate, PermissionSystem 5 levels, terminal binary allowlist, authenticated web bridge, RotatingFileHandler 5MB×3 |
| **Dev Jobs** | Autonomous 5-phase build jobs: Planner → Generator → Scaffold → Verifier → Git; self-heal (3 attempts), syntax validation |
| **Specialists** | Multi-agent delegation: Lead (Jarvis), Coder, Researcher, System — scoped tools per role |
| **MCP** | Connect to any external MCP stdio/HTTP server, auto-register tools into ToolRegistry |
| **Extension** | Chrome/Edge Manifest V3 sidebar, floating pill, context menus, voice dictation, page summarization |
| **REST API** | FastAPI :8768 with Bearer token auth, `/command`, `/health`, SSE `/stream`, `/page-assist` |
| **Model Hub** | Task-based LLM selection + cheap-first cascade: fast cheap model first, upgrade on failure |
| **IDE** | VSCode extension settings, workspace launcher, IDE integration |

---

## New in Phases 5–7

### Phase 5 — Model Hub & Intelligent Routing
- **Model Hub** (`core/brain.py`) — task-based LLM routing: code tasks → Groq code model, vision → Gemini, chat → cheap-first cascade.
- **Cheap-first cascade** — attempts the cheapest capable model first; promotes to smarter model only on failure or low-confidence output.
- **OpenAI Bridge** — drop-in OpenAI-compatible API endpoint for third-party tools to call Flexie's LLM chain.
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
  - `POST /command` — fire a command, get structured JSON response.
  - `GET /stream` — Server-Sent Events stream of assistant speech and state changes.
  - `POST /page-assist` — ask Flexie about a webpage (title, URL, selected text, page content).
  - `POST /approval` — confirm or cancel a DangerGate prompt from an external UI.
  - `GET /health` — liveness probe.
  - Bearer token auth (`utils/udp_auth.py` token shared with WebSocket bridge).
- **Browser Extension** (`extension/`, Manifest V3):
  - Sidebar panel with voice dictation + command input, wired to `:8768` REST API.
  - Floating "Ask Flexie" pill appears on text selection — explain, rewrite, debug.
  - Right-click context menus on any page, image, or code snippet.
  - Permission approval prompts before sensitive page actions.
- **JarvisOrb** (`vision/components/JarvisOrb.tsx`) — React 3D orb UI:
  - WebSocket-connected to Flexie backend at `:8765`.
  - Real-time hand tracking (`HandTracker`) — gesture modes: idle / spin / zoom.
  - Streams `STATE:` / `SAY:` messages from assistant to orb animation.

---

## All Voice/Text Commands

**Tested 75/75 pass via `IntentRouter.route()`:**

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
| **Awareness** | `who are you`, `what can you do` | `awareness` |
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

### Complete Feature List (90 Intents, 41 Engines, 45 Handlers)

**All 90 intents `core/router.py:201` (unique):**

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

**41 Engines `engines/`:** `alarm`, `automation`, `browser`, `code_search`, `developer`, `email_engine`, `files`, `image_gen`, `intelligence`, `knowledge`, `music`, `news`, `pdf_reader`, `system`, `vision`, `weather`, `wiki`, `self_awareness`, + 23 free plugin engines

**45 Handlers `core/handlers/`:** `age`, `alarm`, `automation`, `awareness`, `body_metrics`, `browser`, `clipboard_mgr`, `code_gen`, `code_search`, `color_info`, `converter`, `dev`, `dictionary`, `facts`, `files`, `hash_encoder`, `image_gen`, `ip_lookup`, `jokes`, `json_fmt`, `lorem`, `media`, `memory_system`, `news`, `notification`, `password`, `pdf`, `pomodoro`, `qrcode`, `quotes`, `reminders`, `research`, `search`, `summarize`, `system`, `text_tools`, `tools`, `uuid`, `vision`, `weather`, `wiki`, `agents`, `context`, `dispatcher`

---

## Engines & Stack

| Engine | Tech | Free? |
|---|---|-------|
| Voice | SpeechRecognition, Vosk, edge-tts (neural) + pygame, SAPI fallback, webrtcvad | Yes |
| LLM | Groq (openai/gpt-oss-20b), OpenAI gpt-4o-mini, DeepSeek, Mistral, Gemini 2.0-flash, Claude, Ollama, DDGS fallback | Yes |
| Browser | Playwright 1.52 chromium persistent `browser_session/` | Yes |
| Files | FileManager, PathResolver | Yes |
| Code | CodeSearchEngine, CodeGen, Research (DDG + LLM 618 words) | Yes |
| Weather/News/Wiki | OpenWeather, NewsAPI, Wikipedia | Yes |
| Memory | Chroma PersistentClient, SQLite MemoryManager | Yes |
| Automation | AutomationScheduler (daily/hourly/interval 60s poll) | Yes |
| Vision | VisionEngine + Gemini vision | Yes |
| UI | PyQt6 HUD, WebSocket bridge 8765, UDP 9886/9887 | Yes |

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

**Resource caps** — max 60 files per project, max 300 KB per file, 120s hard cap on any subprocess.

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

`interface/api_server.py` — FastAPI service at `http://127.0.0.1:8768`:

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Liveness probe, returns `{"status":"ok"}` |
| `/command` | POST | Execute any Flexie command, returns structured JSON |
| `/stream` | GET | SSE stream of state changes and assistant speech |
| `/page-assist` | POST | Ask Flexie about a page (url, title, content, selected_text) |
| `/approval` | POST | Confirm or cancel a DangerGate permission prompt |

**Auth:** Bearer token (`Authorization: Bearer <token>`) — same token as WebSocket bridge, written to `.flexie_udp_token`.

```bash
# Start API server
python interface/api_server.py

# Send a command
curl -X POST http://127.0.0.1:8768/command \
  -H "Authorization: Bearer $(cat .flexie_udp_token)" \
  -H "Content-Type: application/json" \
  -d '{"command": "what is the weather in Chennai"}'

# Stream assistant speech
curl -N http://127.0.0.1:8768/stream \
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

- **VectorStore** `core/vector_store.py:18` Chroma `context/flexie_memory/` semantic search `search_episodes(limit=5)` `brain.py:90`.
- **MemoryManager** `core/memory_manager.py:31` `SHORT_TERM/CONVERSATION/PREFERENCES/FACTS/TASKS/WORKSPACE` + `importance*confidence` ranking, `cleanup_expired()`.
- **Auto-extract** `orchestrator.py:405` `my name is`/`i like` → `PREFERENCES/FACTS` + `VectorStore.add_episode`.
- **HybridRouter** `core/hybrid_router.py:82` detects `and/then/,` multi-step → `GoalPlanner` `core/goal_planner.py` → `DAGPlanner` 4 threads.
- **Self-correction** `workflow_executor.py:82` checks `active_document` exists+non-empty, `GoalEvaluator:49` evaluates, retries rephrased via `brain.ask`.

---

## Voice & Streaming

- **VAD** `interface/voice.py` `energy_threshold 150`, `vad_threshold max(noise*1.5,80)`, `webrtcvad.Vad(2)` boost, `is_speaking` 8s stuck watchdog.
- **Mic** Persistent `sr.Microphone` context with `adjust_for_ambient_noise`, COM initialized on Windows.
- **TTS (neural, default)** Edge neural voices via `edge-tts` → temp mp3 → pygame playback. Voice: `FLEXIE_VOICE` (default `en-GB-RyanNeural`, Jarvis-style British male). **Offline fallback**: Windows SAPI via PowerShell `System.Speech` (`_speak_sapi`). Mode switch: `FLEXIE_TTS_MODE=neural|sapi`.
- **Natural pacing** `prepare_speech_text()` strips markdown/emojis/symbols from spoken text (`&`→"and", `%`→"percent", bullets→pauses); `speak()` batches ~2 sentences per clip to avoid choppy per-sentence playback.
- **TTS guard** long replies (>300 chars) truncate at the last **sentence boundary** with "I've posted the full text to your screen." — never mid-word.
- **Streaming** `brain.ask_stream(stream=True)` yields chunks, `orchestrator.speak_stream` splits `(?<=[.!?])` sends `STREAM` UDP `9886` → `web_ui_bridge` WS `8765`.

---

## Safety & Permissions

- **SafetyGuard** `core/safety.py` word-boundary destructive-pattern blocklist (`rm -rf`, `del /s`, `format c:`, `curl|sh`, PowerShell `-enc`) + **metachar sanitization**: `;`/`&&` in spoken queries are stripped instead of rejecting the whole command; raw pipes, backticks and `$(...)` substitution are always rejected. `check()` returns `(ok, sanitized_command)`.
- **DangerGate** `core/danger_gate.py` requires spoken confirmation for `delete`, `format`, payments, sends; negation-aware ("not sure" ≠ "yes").
- **PermissionSystem** `core/permission_system.py` 5 levels `READ_ONLY→DANGEROUS`; `terminal.run` enforces a **binary allowlist** (dev tools only — git/python/pytest/node/npm…), fails closed, hard 120s cap; `python.exec` requires user confirmation and runs through the Docker sandbox when available.
- **Web bridge auth** `interface/web_ui_bridge.py` generates a per-run random token, serves the UI over localhost-only HTTP (no CORS) with the token embedded, and requires an `AUTH:<token>` WebSocket handshake before relaying anything to the orchestrator. `main.py` also publishes the token to `.flexie_udp_token` (gitignored) so a bridge started by hand shares this run's token, and senders fail closed — an unsigned datagram is never sent, because the orchestrator rejects it and the UI then looks "dead" (`utils/udp_auth.py`).
- **Log rotation** `RotatingFileHandler 5MB×3`; all exception handlers log (`logging.debug("[file:line] Swallowed exception…")`) instead of silent `except: pass`.
- **Validation** `utils/config.py` `_validate_env()` warns if `GROQ_API_KEY` missing/invalid; CI lint gate keeps safety modules warning-free.

---

## Getting Started

```bash
# 1. Python 3.10+
python -m venv venv
venv\Scripts\activate

# 2. Install deps (auto on first run via utils/installer.py:29)
pip install -r requirements.txt
# Optional: pip install chromadb webrtcvad docker
# For REST API: pip install fastapi uvicorn

# 3. Playwright
python -m playwright install chromium

# 4. Env
cp .env.example .env
# Edit .env:
# GROQ_API_KEY=gsk_... (from console.groq.com)
# GEMINI_API_KEY=... (optional, needed for vision)
# FLEXIE_EMAIL=... FLEXIE_PASS=... (Gmail app password)
# OPENAI_API_KEY=... (optional, fallback)

# 5. Run core assistant
python main.py  # starts orchestrator + PyQt HUD

# Or run web bridge only
python interface/web_ui_bridge.py  # ws://localhost:8765

# Or run REST/SSE API (for browser extension + external apps)
python interface/api_server.py  # http://localhost:8768

# 6. Browser Extension (optional)
#    chrome://extensions/ → Developer mode → Load unpacked → select extension/

# 7. MCP servers (optional — add to .flexie_mcp.json)
#    npm i -g @modelcontextprotocol/server-filesystem
```

---

## Configuration

`utils/config.py:8` `load_dotenv .env`:

| Var | Default | Purpose |
|---|---|---------|
| `GROQ_API_KEY` | `""` | Groq `openai/gpt-oss-20b` (primary, `brain.py`) |
| `GEMINI_API_KEY` | `""` | Gemini `2.0-flash` `brain.py` (vision + chat fallback) |
| `OPENAI_API_KEY` | `""` | OpenAI GPT-4o-mini (fallback in LLM chain) |
| `FLEXIE_VOICE` | `en-GB-RyanNeural` | Edge neural voice for TTS (e.g. `en-US-GuyNeural`, `en-IN-PrabhatNeural`) |
| `FLEXIE_TTS_MODE` | `neural` | `neural` (Edge TTS) or `sapi` (offline Windows SAPI fallback) |
| `FLEXIE_EMAIL`/`FLEXIE_PASS` | `""` | EmailEngine IMAP/SMTP `engines/email_engine.py:8` |
| `OLLAMA_URL` | `http://localhost:11434` | Local offline fallback `brain.py:150` |
| `LOG_FILE` | `flexie_activity.log` | Rotating 5MB×3 `orchestrator.py:254` |
| `JOBS_DIR` | `workspace/.flexie_jobs` | Autonomous build job workspaces |
| `JOB_MAX_FILES` | `60` | Max files generated per project |
| `JOB_MAX_FILE_SIZE_KB` | `300` | Max file size per generated file |
| `MCP_CONFIG` | `.flexie_mcp.json` | External MCP server definitions |
| `API_PORT` | `8768` | REST/SSE API server port |

---

## Project Structure

```
flexie_v2/
├── core/
│   ├── router.py (TYPO_MAP, NL_OVERRIDES 40+, route)
│   ├── hybrid_router.py (ALWAYS_SIMPLE, COMPLEX_PATTERNS, model hub)
│   ├── orchestrator.py (handle_command, run, speak_stream)
│   ├── brain.py (Groq→OpenAI→DeepSeek→Mistral→Gemini→Anthropic→Ollama→DDG, ask_stream)
│   ├── memory_manager.py (6 categories)
│   ├── workflow_executor.py (verify_step, self-correction)
│   ├── dag_planner.py (ThreadPool 4)
│   ├── goal_planner.py / goal_evaluator.py
│   ├── desktop_control.py / agent_executor.py / tool_registry.py
│   ├── mcp_adapter.py (MCP stdio/HTTP client, tool auto-registration) [NEW]
│   ├── specialists.py (Lead/Coder/Researcher/System agents) [NEW]
│   ├── browser_and_comm_tools.py (browser+email ToolRegistry entries) [NEW]
│   ├── permission_system.py (5-level permission model)
│   ├── capability_registry.py (plugin marketplace foundation)
│   ├── handlers/ (45+ handlers: code_gen, research, automation, agents...)
│   ├── jobs/ [NEW — autonomous dev assistant]
│   │   ├── planner.py (PLAN.md / ACCEPTANCE.md / AGENTS.md generation)
│   │   ├── generator.py (file-by-file codegen, syntax validation, secret scrub)
│   │   ├── scaffold.py (directory + stub creation)
│   │   ├── verifier.py (stack detect, env setup, lint→test→start→heal)
│   │   ├── git_ops.py (init, phase commits, undo)
│   │   ├── manager.py (singleton JobManager, background worker, EventBus)
│   │   ├── models.py (BuildJob, JobPhase, JobStatus)
│   │   └── store.py (job persistence)
│   └── workflow_parser.py (and/then split)
├── engines/
│   ├── automation.py (AutomationScheduler)
│   ├── browser.py (Playwright)
│   ├── files.py (FileManager, PathResolver)
│   ├── code_search.py / email_engine.py / developer.py
│   └── weather, news, vision, etc (40+ engines)
├── interface/
│   ├── voice.py (VAD 150/80 + webrtcvad)
│   ├── ui.py (PyQt6)
│   ├── web_ui_bridge.py (WS 8765 ↔ UDP 9886/9887)
│   └── api_server.py (FastAPI REST+SSE :8768, Bearer auth) [NEW]
├── extension/ [NEW — Chrome/Edge Manifest V3]
│   ├── manifest.json (v3, sidePanel, contextMenus)
│   ├── sidebar.html / sidebar.js / sidebar.css
│   ├── content.js (floating pill, text selection)
│   ├── background.js (service worker, context menus)
│   └── popup.html
├── vision/
│   ├── components/JarvisOrb.tsx (3D orb, hand tracking, WS) [NEW]
│   └── app/globals.css
├── templates/
│   └── react_vite/ (React+Vite scaffold template) [NEW]
├── utils/
│   ├── config.py (_validate_env, model hub config)
│   ├── path_resolver.py (Downloads/Desktop)
│   ├── path_jail.py (workspace escape prevention)
│   └── installer.py (no --upgrade on every start)
├── workspace/ (autonomous job workspaces) [NEW]
├── tests/ (35+ files, 600+ test cases) [EXPANDED]
├── requirements.txt (playwright>=1.52,<2, google-genai>=1.0,<2, ddgs>=8, fastapi, uvicorn)
└── main.py (install_missing + orchestrator.run)
```

---

## Testing

```bash
python -m pytest tests/ -v
# 600+ passed (35+ test files)

# Feature routing check (75 commands)
python -c "from core.router import IntentRouter; r=IntentRouter(); print(r.route('tell me binary search code and save to downloads'))"
# → ('code_gen', 0.95)

# Workflow parser
python -c "from core.workflow_parser import WorkflowParser; print(WorkflowParser.parse_simple_workflow('open notepad and create binary search code and save to downloads'))"
# → True ['open notepad','create binary search code','save to downloads']

# MCP adapter
python -m pytest tests/test_mcp_adapter.py -v

# Specialist agents
python -m pytest tests/test_specialists.py -v

# REST API
python -m pytest tests/test_api_server.py -v
python -m pytest tests/test_page_assistant_api.py -v

# Dev assistant jobs (planner, generator, verifier)
python -m pytest tests/test_jobs.py tests/test_planner.py tests/test_generator.py tests/test_verifier.py -v

# E2E dev assistant (full pipeline)
python -m pytest tests/test_e2e_dev_assistant.py -v

# Permission flow
python -m pytest tests/test_permission_flow.py -v

# IDE integration
python -m pytest tests/test_ide_integration.py -v
```

**Test coverage breakdown (35+ files):**

| Suite | What it covers |
|---|---|
| `test_router.py` | 90 intents, TYPO_MAP, NL_OVERRIDES, 75 voice commands |
| `test_mcp_adapter.py` | stdio spawn, tool discovery, ToolRegistry registration |
| `test_specialists.py` | Lead/Coder/Researcher/System delegation, scoped tools |
| `test_api_server.py` | REST endpoints, Bearer auth, error responses |
| `test_page_assistant_api.py` | /page-assist with page context, selected text |
| `test_e2e_dev_assistant.py` | Full build pipeline from prompt to running server |
| `test_jobs.py` / `test_planner.py` | PLAN.md generation, template matching, fallback |
| `test_generator.py` | Syntax validation, secret scrub, repair attempt |
| `test_verifier.py` | Stack detection, self-heal loop, acceptance criteria |
| `test_permission_flow.py` | 5-level permission model, DangerGate integration |
| `test_ide_integration.py` | VSCode launch, settings injection, extension activation |
| `test_memory_upgrade.py` | Memory migration, category search |
| `test_browser_and_comm_tools.py` | ToolRegistry browser+email entries |
| `test_safety.py` / `test_sandbox.py` | Destructive pattern blocklist, path jail |
| `test_workflow.py` / `test_workflow_executor.py` | DAG execution, self-correction |

---

## Roadmap

**Phase 2 Intelligence ✓** - Memory 5+5, HybridRouter+GoalPlanner, self-correction
**Phase 3 Autonomy ✓** - AutomationScheduler daily/hourly, DesktopControl+AgentExecutor, async browser DAG, webrtcvad
**Phase 4 Experience ✓** - Streaming ask_stream+speak_stream, web dashboard WORKFLOW/STREAM, safety audit
**Phase 5 Model Hub ✓** - Task-based LLM routing, cheap-first cascade, OpenAI bridge
**Phase 6 IDE Integration ✓** - VSCode extension, workspace launcher, React/Vite scaffold template
**Phase 7 Dev Assistant ✓** - 5-phase build jobs, specialist agents, MCP adapter, REST/SSE API, browser extension, JarvisOrb

**Next (Phase 8+):**
- Plugin marketplace `capability_registry.py:23` — publish/install community tools
- Mobile PWA `flexie_web/` — React PWA packaged for Android/iOS
- Vision always-on `vision.py:98` — continuous screen monitoring
- Docker strict sandbox `sandbox/executor.py` — full isolation for untrusted code
- Multi-user — shared memory namespaces, per-user permission profiles
- Voice wakeword — always-on "Hey Flexie" detection without VAD polling

---

## Limitations

- Windows 10/11 only (`pycaw`, `comtypes`, `os.startfile`) — Linux/Mac not supported yet.
- Needs mic permission; `pyaudio` optional but `SpeechRecognition` needs it.
- Groq free tier rate limits — falls back to Gemini/Ollama automatically.
- Vosk model `~/.cache/vosk/vosk-model-small-en-us-0.15` needed for offline STT.
- Playwright `browser_session/` persistent cookies stored on disk.
- VectorStore degrades to `[]` if `chromadb` not installed (`core/vector_store.py:44`).
- `flexie_activity.log` rotated (5MB×3) but can be verbose under heavy workloads.
- MCP servers must be installed separately (e.g. `npm i -g @modelcontextprotocol/server-filesystem`).
- Browser extension requires Developer Mode in Chrome/Edge — not published to web store.
- REST API (`api_server.py`) requires `fastapi` and `uvicorn` — not in base `requirements.txt`, install with `pip install fastapi uvicorn`.
- Dev jobs workspace (`workspace/`) can grow large; no automatic cleanup.
- Captcha detection pauses browser automation — manual intervention required.

---

## License

No LICENSE file is committed yet — add one before distributing (placeholder:
MIT recommended for the app code). Note that `pymupdf` (PyMuPDF) is
**AGPL-licensed**: distributing binaries that link it requires AGPL compliance
or a commercial PyMuPDF license.

---

*Flexie 2.0 — Built for Dhanush. 600+ tests. Voice → Router → Hybrid → ModelHub → Planner → DAG → Specialist → Jobs → MCP → Verify → Memory → Stream → API → Extension.*

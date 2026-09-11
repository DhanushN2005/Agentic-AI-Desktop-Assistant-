# Flexie 2.0 — Autonomous Agentic AI Desktop Assistant

> **Resume:** *Flexie 2.0 — Agentic AI Desktop Assistant — A Windows-native AI agent capable of voice interaction, multi-step task planning, tool execution, desktop automation, memory, web research, code generation, and task verification.*
> **GitHub:** *Flexie 2.0 — Autonomous Agentic AI Desktop Assistant — AI Agent is the core identity; voice, chatbot, automation, and desktop control are capabilities of the agent.*

A **zero-config, Windows-native autonomous AI agent** with 30+ free plugins, self-awareness, persistent memory, hybrid agentic routing, browser automation, and automation scheduler — all running locally on Windows.

**LLM Chain:** Groq `llama-3.1-8b-instant` → Gemini `1.5-flash` → Ollama → DuckDuckGo fallback. Streaming, VAD, desktop control, and self-correction included.

---

## Table of Contents
- [What Flexie Is](#what-flexie-is)
- [Architecture Overview](#architecture-overview)
- [Core Features](#core-features)
- [All Voice/Text Commands](#all-voicetext-commands)
- [Engines & Stack](#engines--stack)
- [What Flexie Can Do](#what-flexie-can-do)
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

Flexie is a **desktop-native autonomous AI agent** — *AI Agent is the core identity; voice, chatbot, automation, and desktop control are capabilities of the agent.*

It listens to voice (VAD) or keyboard (PyQt6 HUD), understands natural language, **plans multi-step tasks** (`GoalPlanner` + `DAGPlanner`), **executes tools** (`ToolRegistry` 30 tools, `DesktopControl`, `BrowserEngine`), **remembers** (VectorStore + MemoryManager), and **verifies** (`GoalEvaluator` + self-correction) — not just chat.

**Resume title:** *Flexie 2.0 — Agentic AI Desktop Assistant* — A Windows-native AI agent capable of voice interaction, multi-step task planning, tool execution, desktop automation, memory, web research, code generation, and task verification.

**GitHub title:** *Flexie 2.0 — Autonomous Agentic AI Desktop Assistant*

**Not a cloud SaaS** — data stays on your machine. External calls only to free LLM APIs (Groq, Gemini) and free public APIs (weather, news, Wikipedia).

**359 tests pass.**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│ USER INPUT: Voice (VAD RMS+webrtcvad) / Keyboard│
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ INTENT ROUTER (core/router.py)                  │
│  TYPO_MAP (difflib 0.85) + NL_OVERRIDES (40+ regex) + Compiled Triggers │
│  → Intent + Confidence (0.0-1.0)                │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ HYBRID ROUTER (core/hybrid_router.py)           │
│  Simple (<50ms) → Deterministic                 │
│  Complex (and/then, len>8, conf<0.7) → GoalPlanner │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ ORCHESTRATOR (core/orchestrator.py)             │
│  TaskClassifier → WorkflowParser → DAGPlanner (4 threads) │
│  → WorkflowExecutor → AgentExecutor (observe-act-verify) │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ HANDLERS → ENGINES → DESKTOP/BROWSER/VISION     │
│  30+ handlers, 40 engines, DesktopControl, BrowserEngine (Playwright) │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│ MEMORY + BRAIN (core/brain.py)                  │
│  VectorStore Chroma (5) + MemoryManager (5) → ContextCompiler → LLM │
│  Streaming (Groq stream=True) → speak_stream     │
└─────────────────────────────────────────────────┘
```

**Key modules:**
- `core/router.py` - TYPO_MAP, NL_OVERRIDES, compiled triggers, route()
- `core/hybrid_router.py` - ALWAYS_SIMPLE, COMPLEX_PATTERNS, classify()
- `core/goal_planner.py` - TaskGraph decomposition
- `core/dag_planner.py` - ThreadPoolExecutor 4, blocking_execute
- `core/workflow_executor.py` - sequential + verify_step + GoalEvaluator retry
- `core/memory_manager.py` - 6 categories, SQLite, search
- `core/brain.py` - Groq→Gemini→Ollama→DDG, ask_stream
- `interface/voice.py` - RMS VAD + webrtcvad, energy 150, threshold 80

---

## Core Features

| Area | Features |
|---|---|
| **Voice** | VAD RMS+webrtcvad, barge-in, Indian English en-IN, PowerShell TTS, streaming, 8s stuck watchdog |
| **Browser** | Playwright persistent context, navigate/click/fill/scroll, multi-tab research parallel (DAG), gmail_read, ad skip |
| **Files** | create/rename/delete, organize desktop, Downloads/Desktop/Documents resolver `utils/path_resolver.py` |
| **Code** | Local search `engines/code_search.py`, generation `handlers/code_gen.py` (python/java/js etc) → `Downloads/binary_search.py` |
| **Research** | Web search DDG + LLM 300+ words summary `handlers/research.py` → save to file |
| **Automation** | `engines/automation.py` daily/hourly/interval, built-in daily briefing 9am + auto organize 6pm |
| **Memory** | VectorStore 5 + MemoryManager 5, auto-extract `my name is`/`i like` → PREFERENCES/FACTS |
| **Safety** | SafetyGuard blacklist, DangerGate, PermissionSystem 5 levels, RotatingFileHandler 5MB×3 |

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

|---:|---|---|---|---|
|---|--------|---------|---------------|----------|
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
| Voice | SpeechRecognition, Vosk, PowerShell System.Speech, webrtcvad | Yes |
| LLM | Groq llama-3.1-8b-instant, Gemini 1.5-flash, Ollama tinyllama, DDGS | Yes |
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

- **VAD** `interface/voice.py:12` `energy_threshold 150` (was 300), `vad_threshold max(noise*1.5,80)` (was 1.8/120), `webrtcvad.Vad(2)` boost `voice.py:310`, `is_speaking` 8s timeout `voice.py:295`.
- **Mic** Persistent `sr.Microphone` `voice.py:47` `adjust_for_ambient_noise 1.5s`, `interrupt_monitor` disabled to avoid conflict `voice.py:137`.
- **TTS** PowerShell `System.Speech` `voice.py:58` Rate/Volume, `is_speaking` flag mutes VAD, queue `_speech_queue` `orchestrator.py:101`.
- **Streaming** `brain.py:157` `ask_stream(stream=True)` yields chunks, `orchestrator.py:308` `speak_stream` splits `(?<=[.!?])` sends `STREAM` UDP `9886` → `web_ui_bridge.py:39` WS `8765`.

---

## Safety & Permissions

- **SafetyGuard** `core/safety.py:6` blacklist `rm -rf`, `del /s`, `sudo`, `remove-item` → `validate()`.
- **DangerGate** `core/danger_gate.py:14` confirms `delete`, `format`.
- **PermissionSystem** `core/permission_system.py:26` 5 levels `READ_ONLY→DANGEROUS` used by `core/desktop_control.py:34` `DesktopControl` (pyautogui FAILSAFE).
- **Shell** `engines/developer.py:23` `git` uses list form `["git","status"]` not `shell`, `files.py:69` prefers `os.startfile`.
- **Log rotation** `core/orchestrator.py:254` `RotatingFileHandler 5MB×3`.
- **Validation** `utils/config.py:5` `_validate_env()` warns if `GROQ_API_KEY` missing/invalid, `voice.py:46` mic permission.

---

## Getting Started

```bash
# 1. Python 3.10+
python -m venv venv
venv\Scripts\activate

# 2. Install deps (auto on first run via utils/installer.py:29)
pip install -r requirements.txt
# Optional: pip install chromadb webrtcvad docker

# 3. Playwright
python -m playwright install chromium

# 4. Env
cp .env.example .env
# Edit .env:
# GROQ_API_KEY=gsk_... (from console.groq.com)
# GEMINI_API_KEY=... (optional)
# FLEXIE_EMAIL=... FLEXIE_PASS=... (app password)

# 5. Run
python main.py  # starts orchestrator + PyQt HUD
# Or web UI
python interface/web_ui_bridge.py  # ws://localhost:8765
```

---

## Configuration

`utils/config.py:8` `load_dotenv .env`:

| Var | Default | Purpose |
|---|---|---------|
| `GROQ_API_KEY` | `""` | Groq `llama-3.1-8b-instant` `brain.py:94` |
| `GEMINI_API_KEY` | `""` | Gemini `1.5-flash` `brain.py:106` |
| `FLEXIE_EMAIL`/`FLEXIE_PASS` | `""` | EmailEngine IMAP/SMTP `engines/email_engine.py:8` |
| `OLLAMA_URL` | `http://localhost:11434` | Local fallback `brain.py:150` |
| `LOG_FILE` | `flexie_activity.log` | Rotating 5MB×3 `orchestrator.py:254` |

---

## Project Structure

```
flexie_v2/
├── core/
│   ├── router.py (TYPO_MAP, NL_OVERRIDES 40+, route)
│   ├── hybrid_router.py (ALWAYS_SIMPLE, COMPLEX_PATTERNS)
│   ├── orchestrator.py (handle_command, run, speak_stream)
│   ├── brain.py (Groq→Gemini→Ollama→DDG, ask_stream)
│   ├── memory_manager.py (6 categories)
│   ├── workflow_executor.py (verify_step, self-correction)
│   ├── dag_planner.py (ThreadPool 4)
│   ├── goal_planner.py / goal_evaluator.py
│   ├── desktop_control.py / agent_executor.py / tool_registry.py
│   ├── handlers/ (30+ handlers: code_gen, research, automation...)
│   └── workflow_parser.py (and/then split)
├── engines/
│   ├── automation.py (AutomationScheduler)
│   ├── browser.py (Playwright)
│   ├── files.py (FileManager, PathResolver)
│   ├── code_search.py / email_engine.py / developer.py
│   └── weather, news, vision, etc (40 engines)
├── interface/
│   ├── voice.py (VAD 150/80 + webrtcvad)
│   ├── ui.py (PyQt6)
│   └── web_ui_bridge.py (WS 8765 ↔ UDP 9886/9887)
├── utils/
│   ├── config.py (_validate_env)
│   ├── path_resolver.py (Downloads/Desktop)
│   └── installer.py (no --upgrade on every start)
├── tests/ (359 tests)
├── requirements.txt (playwright>=1.52, google-genai>=0.8.0, ddgs>=8)
└── main.py (install_missing + orchestrator.run)
```

---

## Testing

```bash
python -m pytest tests/ -v
# 359 passed in ~32s

# Feature routing check (75 commands)
python -c "from core.router import IntentRouter; r=IntentRouter(); print(r.route('tell me binary search code and save to downloads'))"
# → ('code_gen', 0.95)

# Workflow
python -c "from core.workflow_parser import WorkflowParser; print(WorkflowParser.parse_simple_workflow('open notepad and create binary search code and save to downloads'))"
# → True ['open notepad','create binary search code','save to downloads']
```

---

## Roadmap

**Phase 2 Intelligence ✓** - Memory 5+5, HybridRouter+GoalPlanner, self-correction
**Phase 3 Autonomy ✓** - AutomationScheduler daily/hourly, DesktopControl+AgentExecutor, async browser DAG, webrtcvad
**Phase 4 Experience ✓** - Streaming ask_stream+speak_stream, web dashboard WORKFLOW/STREAM, safety audit

**Next Level 5:**
- Plugin marketplace `capability_registry.py:23`
- Mobile PWA `flexie_web/`
- Vision always-on `vision.py:98`
- Docker strict `sandbox/executor.py`

---

## Limitations

- Windows 10/11 only (`pycaw`, `comtypes`, `os.startfile`).
- Needs mic permission, `pyaudio` optional but `SpeechRecognition` needs it.
- Groq free tier rate limits - falls back to Gemini/Ollama.
- Vosk model `~/.cache/vosk/vosk-model-small-en-us-0.15` needed for offline.
- Playwright `browser_session/` persistent cookies stored on disk.
- VectorStore degrades to `[]` if `chromadb` not installed `core/vector_store.py:44`.
- `flexie_activity.log` rotated but still verbose.

---

*Flexie 2.0 — Built for Dhanush. 359 tests. Voice → Router → Hybrid → Planner → DAG → Verify → Memory → Stream.*

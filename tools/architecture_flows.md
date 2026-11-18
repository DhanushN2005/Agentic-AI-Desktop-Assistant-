Flexie runs as several cooperating processes that talk over localhost sockets. Ports and files below are the defaults in `utils/config.py`, `utils/udp_auth.py` and `main.py`.

```mermaid
flowchart LR
    subgraph P1["Process 1: python main.py"]
        ORCH["FlexieOrchestrator<br/>action worker, speech worker,<br/>loops, command log"]
        VOICE["VoiceInterface<br/>mic + ASR + TTS"]
        API["REST + SSE API (uvicorn thread)<br/>127.0.0.1:8768"]
        UDPIN["UDP receive loop<br/>127.0.0.1:9887 (signed)"]
        BRAIN["Brain + providers"]
    end

    subgraph P2["Process 2: interface/ui.py (PyQt6 HUD)"]
        QT["Qt window + orb<br/>UDP receive :9886"]
    end

    subgraph P3["Process 3: interface/web_ui_bridge.py"]
        HTTP["HTTP :8766<br/>serves web_ui.html with token"]
        WSB["WebSocket :8765<br/>Host + Origin check, AUTH:token"]
    end

    subgraph P4["Process 4 (on demand): vision/ npm run dev"]
        ORB["Next.js orb UI<br/>first free port from 3000"]
    end

    subgraph EXT["Browser"]
        EXTN["Flexie extension<br/>(Manifest V3)"]
        DASH["Dashboard page<br/>localhost:8766"]
    end

    VOICE --> ORCH
    ORCH --> BRAIN
    ORCH -->|"signed UDP :9886"| QT
    ORCH -->|"signed UDP :9888"| WSB
    QT -->|"signed UDP :9887"| UDPIN
    WSB -->|"signed UDP :9887"| UDPIN
    UDPIN --> ORCH
    DASH --> HTTP
    DASH <--> WSB
    EXTN -->|"Bearer token"| API
    API --> ORCH
    QT -. "starts and stops" .-> P3
    ORCH -. "open vision mode" .-> ORB
    ORB -. "ws to :8765 is rejected by the hardened bridge" .-> WSB
```

```mermaid
flowchart TB
    subgraph DB["SQLite databases (shared WAL connection per file)"]
        D1["data/telemetry.db<br/>LLM calls: tokens, cost, latency, failures"]
        D2["data/traces.db<br/>command traces and steps"]
        D3["data/memory_structured.db<br/>MemoryManager entries"]
        D4["flexie_memory.db, flexie_awareness.db,<br/>flexie_global_profile.db, clipboard_history.db"]
    end
    subgraph FILES["Files and folders"]
        F1["context/flexie_memory/<br/>Chroma vector store"]
        F2["workspace/.flexie_jobs/*.json<br/>build job state"]
        F3["flexie_activity.log, flexie_telemetry.log<br/>rotating logs"]
        F4[".flexie_udp_token, .flexie_ui_ports<br/>per-run auth and UI subscribers"]
        F5["browser_session/<br/>Playwright profile"]
        F6["automation_jobs.json, knowledge_index.json<br/>scheduler jobs, file index"]
        F7["Downloads/ job project folders<br/>Downloads/Flexie Images/"]
    end
    BRAINX["Brain + telemetry"] --> D1
    TRACEX["TraceCollector"] --> D2
    MEMX["MemoryManager / MemoryFacade"] --> D3
    ENGX["Memory, awareness, profile, clipboard engines"] --> D4
    VSX["VectorStore"] --> F1
    JOBX["JobManager"] --> F2
    LOGX["logging"] --> F3
    MAINX["main.py + udp_auth"] --> F4
    BRW["BrowserEngine"] --> F5
    SCHED["AutomationScheduler + KnowledgeEngine"] --> F6
    GENX["Build jobs + image downloader"] --> F7
```
<!--SPLIT-->
### 2.1 Startup (`main.py`)

```mermaid
sequenceDiagram
    participant M as main.py
    participant I as utils/installer
    participant O as FlexieOrchestrator
    participant B as Brain
    participant UI as run_ui() child process
    participant A as API server thread

    M->>I: install_missing()
    M->>M: check_single_instance()
    M->>M: create FLEXIE_UDP_TOKEN, publish to .flexie_udp_token, reset UI port list
    M->>UI: start interface/ui.py (starts the web bridge too)
    M->>O: FlexieOrchestrator()
    O->>O: memory, router, engines, tool registry, specialists, MCP manager, self model
    O-->>B: providers built in a background thread
    O-->>O: vector store initialised in a background thread
    M->>A: port 8768 free? start FastAPI in a thread (else log an error)
    M->>M: wrap handle_command with FlexieController.execute
    M->>O: run()
    O->>O: start worker threads, speak "systems are live", enter the listen loop
    Note over M,O: on exit: stop UI + bridge, kill our own Playwright/Chrome children, cleanup each step in isolation
```

### 2.2 Threads and queues inside the orchestrator

```mermaid
flowchart LR
    subgraph LISTEN["Main thread: run() loop"]
        L1["voice.listen()"] --> L2{"wake word<br/>or already awake?"}
        L2 -->|no| L3["log [WAKE] ignored,<br/>hint at most once a minute"]
        L2 -->|yes| L4["ack ('Okay.') and put text on cmd_queue"]
    end
    UDPT["network loop thread<br/>(UDP 9887, signed)"] --> CQ
    APIQ["REST /command"] --> CQ
    L4 --> CQ[("cmd_queue")]
    CQ --> AW["action worker thread<br/>(COM initialised, one command at a time)"]
    AW --> HC["handle_command"]
    HC --> SPK["speak()"]
    SPK --> SQ[("speech queue")]
    SQ --> SW["speech worker thread<br/>TTS never blocks the action worker"]
    WD["watchdog thread<br/>90 s hang detector"] -.-> AW
    REM["reminder loop<br/>(due reminders by id)"] --> SPK
    AUTO["AutomationScheduler thread<br/>(next_run, persisted)"] --> CQ
    INTEL["intelligence loop<br/>proactive suggestions"] --> SPK
    SAVE["auto-save loop"] -.-> OS1["active window save"]
    MAINT["Brain maintenance thread<br/>expire memory, hourly prune tasks"] -.-> MEMS["memory stores"]
```

### 2.3 `handle_command` in detail

```mermaid
flowchart TD
    A["handle_command(text)"] --> B["trace start, usage scope per command,<br/>clear untrusted-content taint"]
    B --> C["FlexieController.execute (wrapped in main.py)"]
    C --> D{"SafetyGuard<br/>blocked?"}
    D -->|yes| D1["'blocked' + spoken refusal"]
    D -->|no| E{"pending confirmation?"}
    E -->|"yes: yes / no / unrelated"| E1["approve and run, cancel, or re-prompt<br/>(expires after 60 s)"]
    E -->|no| F{"DangerGate flags<br/>a clause?"}
    F -->|yes| F1["create approval request<br/>ask to confirm"]
    F -->|no| G["_resolve_route"]
    G --> G1["1 NL override >= 0.95"] --> G2["2 route cache"] --> G3["3 IntentRouter.route"] --> G4["4 learned route if confidence < 0.8"]
    G4 --> H{"classification"}
    H -->|"simple compound (A and B)"| I["WorkflowParser: all steps Tier-1?<br/>run them, else semantic planning"]
    H -->|"ambiguous or complex"| J["router.route_dynamic (LLM) -> GoalPlanner steps"]
    H -->|"single intent"| K["dispatch_intent"]
    I --> K
    J --> L["execute_workflow: DAG / sequential + verify + retry"]
    L --> K
    K --> M["handler (core/handlers) -> engine / tool / brain"]
    M --> N["speak() reply, update UI"]
    N --> O["command log entry: intent, ok, error, reply, ms"]
    O --> P["trace finish, usage attached, telemetry line"]
```

### 2.4 Voice in and out

```mermaid
flowchart LR
    MIC["Microphone<br/>(persistent stream, calibrated noise floor)"] --> VAD["VAD: energy threshold + webrtcvad,<br/>min speech length, silence timeout"]
    VAD --> ASR["Google ASR"]
    ASR -->|"failed"| OFF["offline decoders<br/>(Vosk / Whisper if installed)"]
    ASR --> TXT["text"]
    OFF --> TXT
    TXT --> WAKE{"wake word or awake?"}
    WAKE -->|yes| CMD["command -> cmd_queue"]
    WAKE -->|no| HINT["log + occasional 'I'm asleep' hint"]

    REPLY["orchestrator.speak(text)"] --> GUARD["TTSGuard: drop repeats,<br/>trim to a sentence boundary (>300 chars)"]
    GUARD --> PREP["prepare_speech_text: strip markdown and emoji"]
    PREP --> TTS{"mode"}
    TTS -->|neural| EDGE["Edge TTS -> mp3 -> pygame"]
    TTS -->|"sapi or edge failed"| SAPI["Windows SAPI via PowerShell<br/>(text passed in an environment variable)"]
    GUARD --> UI["full text to the UI (SAY)"]
```

### 2.5 Tool execution and permissions

```mermaid
flowchart TD
    T["ToolRegistry.execute(tool, args)"] --> T1{"known and enabled?"}
    T1 -->|no| X1["fail: unknown / disabled"]
    T1 -->|yes| T2["PermissionSystem.check_permission<br/>effective level = standing level or active grant,<br/>untrusted-content taint blocks effectful tools"]
    T2 -->|denied| X2["fail: permission denied (needs approval)"]
    T2 -->|ok| T3["CapabilityPolicy.validate_tool<br/>(undeclared capabilities refused)"]
    T3 -->|denied| X3["fail: capability denied"]
    T3 --> T4["normalize_args: types, bounds, defaults<br/>(bool is not int, NaN rejected)"]
    T4 --> T5["mark untrusted if the tool returns third-party content"]
    T5 --> T6{"thread-affine tool?"}
    T6 -->|yes| T7["run inline, flag slow if over the limit"]
    T6 -->|no| T8["run on a worker pool with a timeout<br/>(timeout = outcome unknown; non-idempotent calls are not re-run)"]
    T7 --> R["ActionResult"]
    T8 --> R
    R --> V["AgentExecutor: verify (tri-state)"]
```

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Pending: DangerGate flags a clause (request id)
    Pending --> Approved: pure approval phrase
    Pending --> Rejected: no / cancel
    Pending --> Expired: TTL
    Approved --> Granted: one-shot grant for that request (60 s)
    Granted --> Consumed: command ran
    Consumed --> Idle
    Rejected --> Idle
    Expired --> Idle
```

### 2.6 `Brain.ask`

```mermaid
flowchart TD
    Q["ask(prompt, image?, system override?)"] --> K["cache key: prompt, image path/size/mtime,<br/>history, provider + model signature"]
    K --> H{"cache hit and fresh (45 s)<br/>and not time-sensitive?"}
    H -->|yes| RET["return cached answer"]
    H -->|no| C["_ask_impl"]
    C --> RAG["optional RAG: vector episodes + memory search<br/>(conversation excluded) -> ContextCompiler"]
    RAG --> LF{"local-first and no image?"}
    LF -->|yes| OL["local engine (Ollama), bounded timeout"]
    OL -->|accepted| DONE
    LF -->|no| CH
    OL -->|"empty / invalid"| CH["cloud chain (image: Gemini only)<br/>Groq main -> Groq siblings -> OpenAI -> DeepSeek -> Mistral -> Gemini -> Anthropic"]
    CH --> ACC{"accept(): non-empty and<br/>passes validate (JSON etc.)?"}
    ACC -->|yes| DONE["return text, store in cache"]
    ACC -->|no| NEXT["next provider; circuit breaker records the failure"]
    NEXT --> CH
    CH -->|"all failed"| FF{"image?"}
    FF -->|yes| VF["vision-unavailable message (uncacheable)"]
    FF -->|no| FALL["JSON callers: empty string<br/>otherwise web-search or offline notice (uncacheable)"]
    DONE --> TEL["track_llm: tokens, cost, latency, provider, failures"]
```

### 2.7 Memory: remember, recall, forget

```mermaid
flowchart LR
    SAY["'remember that I like tea'"] --> H["memory handler"]
    H --> F["MemoryFacade.remember"]
    F --> S["scrub secrets"]
    S --> MM["MemoryManager<br/>(SQLite + token index, TTL)"]
    S --> MS["MemorySystem"]
    S --> ME["MemoryEngine"]
    S --> SA["SelfAwareness facts"]
    S -->|"not a secret"| VS["VectorStore episodes"]
    Q["Brain.ask / 'what do you remember'"] --> SR["MemoryManager.search<br/>overlap x importance x confidence x recency"]
    SR --> CC["ContextCompiler: fenced as data"]
    FG["'forget X'"] --> FA["MemoryFacade.forget: every store<br/>(chat, turns, activity, session log, saved replies,<br/>profile, wiki copies, vector scan)"]
    MT["maintenance thread, hourly"] --> PR["prune: expired entries, old rows, old vectors"]
```

### 2.8 Autonomous build job

```mermaid
stateDiagram-v2
    [*] --> Queued: create_job (spec, folder, own git repo)
    Queued --> Running: worker thread picks it up
    Running --> Paused: pause
    Paused --> Running: resume
    Running --> Done: all phases passed
    Running --> Failed: a phase failed (model down, syntax, verify)
    Failed --> Running: resume or fix
    Queued --> Cancelled: cancel
    Running --> Cancelled: cancel
    Done --> [*]
    Failed --> [*]: empty workspace is removed
    Cancelled --> [*]: empty workspace is removed
```

```mermaid
flowchart LR
    P1["scaffold<br/>PLAN.md, ACCEPTANCE.md, AGENTS.md,<br/>template files, git commit"] --> P2["core_logic<br/>generate source files"]
    P2 --> P3["ui<br/>generate UI files"]
    P3 --> P4["tests_and_lint"]
    P4 --> P5["verify_and_launch<br/>run / smoke test /<br/>static: linked files are real"]
    P5 --> OK["done"]
    P5 -->|problems| HEAL["self-heal, up to 3 attempts"]
    HEAL --> P5
    EV["EventBus events: started, phase, done"] -.-> UI["UI / voice announcements"]
```

### 2.9 MCP servers

```mermaid
sequenceDiagram
    participant C as .flexie_mcp.json
    participant M as MCPManager
    participant S as MCP server process (stdio)
    participant R as ToolRegistry
    participant G as PermissionSystem
    C->>M: servers (name, command, args, readOnlyTools)
    M->>S: spawn (own process group), initialize, tools/list
    S-->>M: tool list
    M->>R: register mcp__server__tool (default: confirm, read-only only if listed)
    Note over M,S: stderr drained, requests have ids, server-initiated messages never complete a request
    R->>G: effectful call needs approval
    G-->>R: approved
    R->>S: tools/call
    S-->>R: result
    R->>R: cap output (8 KB), wrap as untrusted, mark the command tainted
```

### 2.10 Planning and specialists

```mermaid
flowchart TD
    A["complex request"] --> GP["GoalPlanner (LLM -> JSON steps)<br/>steps sanitised: known tools only"]
    GP --> RB["RunBudget: steps, time, repeated-action cycle detection"]
    RB --> AX["AgentExecutor: observe -> act -> verify"]
    AX --> SR["ScopedToolRegistry per role"]
    SR --> LEAD["Lead: decompose and synthesise"]
    SR --> COD["Coder: files, terminal, tests, git"]
    SR --> RES["Researcher: browser, search, summarise"]
    SR --> SYS["System: desktop, windows, volume, apps"]
    LEAD --> TR["ToolRegistry.execute (section 2.5)"]
    COD --> TR
    RES --> TR
    SYS --> TR
    TR --> GE["GoalEvaluator: tri-state result"]
    GE -->|"not done"| AX
    GE -->|done| OUT["reply"]
```

### 2.11 REST API and browser extension

```mermaid
sequenceDiagram
    participant P as Web page
    participant CS as content.js (pill, selection)
    participant BG as background.js (service worker)
    participant SB as sidebar.js
    participant API as api_server.py :8768
    participant O as Orchestrator
    P->>CS: user selects text
    CS->>BG: message (sender checked, privileged endpoints refused)
    SB->>BG: CALL_API request
    BG->>BG: validate endpoint against the allow-list
    BG->>API: fetch with Bearer token
    API->>API: Host, Origin and token checks, size limits
    alt /command
        API->>O: cmd_queue.put (429 when full)
        API-->>BG: queued
    else /page-assist
        API->>O: Brain call with page context
        API-->>BG: answer
    else mail send / reply
        API->>API: wait for /approve (request id)
        API-->>BG: 403 if not approved, nothing sent
    end
    BG-->>SB: response, toast / panel update
```

### 2.12 Telemetry, traces and events

```mermaid
flowchart LR
    CMD["handle_command"] --> TS["TraceCollector.start (trace id)"]
    CMD --> UT["begin_command: usage scope (ContextVar)"]
    BR["Brain / provider call"] --> TL["track_llm: tokens, cost, latency, failure"]
    TL --> UT
    UT --> TR["trace.metadata.usage"]
    TS --> ST["TraceStore: traces.db"]
    TL --> TST["telemetry store: telemetry.db<br/>(failed column, 30-day retention)"]
    TST --> RP["report / /api/flexie/usage"]
    EB["EventBus<br/>(priority, sequence, trace id)"] --> TC["trace collector attaches events"]
```

### 2.13 Screen, images and vision mode

```mermaid
flowchart TD
    S1["'check / summarize my screen'"] --> S2["screenshot (pyautogui)"]
    S2 --> S3["downscale to 1280 px, ask a vision model<br/>(Gemini; model fallback on 404/503)"]
    S3 -->|answer| S4["speak the description"]
    S3 -->|"no vision model answered"| S5["OCR the screenshot (Tesseract)"]
    S5 -->|text| S6["say the model failed, read the text"]
    S5 -->|none| S7["say vision is unavailable"]

    I1["'download 5 images of cats'"] --> I2["DuckDuckGo image search or images on a page URL"]
    I2 --> I3{"public http(s) host?<br/>redirects re-checked"}
    I3 -->|no| I4["skip"]
    I3 -->|yes| I5["size cap, image content type, decodes as an image, no duplicates"]
    I5 --> I6["Downloads/Flexie Images/topic-time/"]

    V1["'open vision mode'"] --> V2{"vision/node_modules?"}
    V2 -->|no| V3["npm ci (first run)"]
    V2 -->|yes| V4
    V3 --> V4["npm run dev on a free port from 3000"]
    V4 --> V5["wait until it answers, open the browser"]
    V6["'close vision mode' / Flexie exit"] --> V7["kill the dev server tree"]
```

### 2.14 Tests, evals and CI

```mermaid
flowchart LR
    DEV["code change"] --> RUFF["ruff check ."]
    DEV --> PT["pytest tests<br/>(70 files, conftest isolates build output)"]
    DEV --> RE["evals.run: routing, 158 cases, gate 0.9"]
    DEV --> AE["evals.agent_run: 59 deterministic agent cases"]
    DEV --> BN["evals.bench: latency table, import times"]
    RUFF --> CI
    PT --> CI
    RE --> CI
    AE --> CI
    CI["GitHub Actions ci.yml<br/>Python matrix, coverage floor 36%,<br/>strict lint on safety modules"] --> RES["pass / fail"]
    BN --> REP["evals/results/bench-*.json and .md"]
    RE --> REP
```
<!--SPLIT-->
### 4.1 Browser extension (`extension/`)

```mermaid
flowchart LR
    MAN["manifest.json<br/>MV3, permissions: activeTab, scripting, storage,<br/>contextMenus, sidePanel, tabs, alarms<br/>host: 127.0.0.1:8768 / localhost:8768"]
    MAN --> BG["background.js<br/>service worker: context menus, alarms,<br/>endpoint allow-list, sender checks, API calls"]
    MAN --> CS["content.js<br/>injected in every page: selection pill, page text extraction"]
    MAN --> SBP["sidebar.html / sidebar.js / sidebar.css<br/>side panel: health check, command box, page assist, voice dictation"]
    MAN --> POP["popup.html<br/>toolbar popup"]
    CS --> BG
    SBP --> BG
    BG --> API["Flexie REST API :8768"]
    BG --> ST["chrome.storage (token, page context)"]
```

### 4.2 Web client and orb UI

```mermaid
flowchart TB
    subgraph WEB["flexie_web/ (React + Vite)"]
        W1["src/App.tsx<br/>dashboard UI, settings, WebSocket client"]
        W2["src/lib/handTracker.ts, gestureMapper.ts, useGestureControl.ts<br/>MediaPipe hand gestures -> commands"]
        W3["src/main.tsx, index.css, App.css"]
    end
    subgraph ORB["vision/ (Next.js + Three.js + MediaPipe)"]
        O1["app/page.tsx, layout.tsx, globals.css"]
        O2["components/JarvisOrb.tsx<br/>HUD, WebSocket client, input handling"]
        O3["lib/orbScene.ts<br/>Three.js scene, bloom"]
        O4["lib/handTracker.ts<br/>pinch to spin, two hands to zoom"]
        O1 --> O2
        O2 --> O3
        O2 --> O4
    end
    WEB -. "ws://localhost:8765" .-> BR["web_ui_bridge.py"]
    ORB -. "ws://127.0.0.1:8765" .-> BR
    BR -. "rejects other origins and clients without AUTH" .-> X["both UIs run standalone today"]
    LAUNCH["engines/vision_mode.py<br/>npm ci + npm run dev"] --> ORB
```

### 4.3 Templates, skills and data

```mermaid
flowchart LR
    subgraph TPL["templates/ (used by core/jobs)"]
        T1["static_site: index.html, script.js, style.css"]
        T2["flask_api: app.py, requirements.txt, test_app.py"]
        T3["react_vite: package.json, vite.config.js, src/"]
        T4["cli_tool: main.py, requirements.txt, test_cli.py"]
        TM["each has manifest.json (trigger words, files, run and test commands)"]
    end
    PL["core/jobs/planner.match_template"] --> TM
    SC["core/jobs/scaffold"] --> TPL

    subgraph SK["skills/"]
        K1["code-explainer/SKILL.md"]
        K2["research-and-summarize/SKILL.md"]
    end
    SL["core/skills loader + catalog<br/>(validated names, escaped, cached by mtime)"] --> SK
    SL --> SP["catalog appended to the system prompt"]

    subgraph PERS["data/persona/ (user-owned)"]
        PS1["SOUL.md, USER.md, MEMORY.md"]
    end
    PR["core/persona.py"] --> PERS
    PR --> SP
```

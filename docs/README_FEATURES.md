# Flexie 2.0: Comprehensive Feature & Limitation Guide

Flexie 2.0 is an advanced desktop AI assistant built for high-performance automation and intelligent interaction. This document outlines every capability, current constraint, and known edge case of the system.

---

## 🎨 1. UI/UX & Aesthetics (Qt floating-orb HUD + web dashboard on request)
**Category: Interface & Visualization**
`python main.py` starts the **PyQt6 HUD** (`interface/ui.py`) as its own process: a 300x300 always-on-top **floating orb**, a **Ctrl+F** spotlight popup, a tray icon (*Show Controls*, *Wake Flexie*, *Exit*), an API-keys dialog and an approval popup. Nothing opens a browser or starts the web bridge at launch. The **web dashboard** (`http://localhost:8766/`, served by `interface/web_ui_bridge.py`, token injected) opens only when you ask ("open web ui", "open vision mode", or the HUD's dashboard button). A replacement of the HUD by the dashboard plus a tray/hotkey launcher was built and then reverted at the user's request; the dashboard kept the pieces below.
*   **Glassmorphism Dashboard:** A semi-transparent frosted-glass page with a chat/command bar, streaming replies and toast notifications.
*   **Reactive Waveform:** A visualizer that follows Flexie's voice-processing states (state updates arrive over the authenticated WebSocket).
*   **System Metrics:** CPU, RAM and battery bars, with a warning toast above 90 % CPU.
*   **Hardware Control Sliders:** System volume and screen brightness.
*   **AI Core Switcher:** Hot-swappable personality modes (Professional, Hacker, Focus, etc.) from the mode selector.
*   **Orb tab:** the 3D hand-gesture orb as a full-window overlay inside the dashboard (see section 6).
*   **Approval dialog:** a risky command raises a modal with Approve / Reject (Esc rejects); it sends `APPROVE:<id>` / `REJECT:<id>` for that request.
*   **API keys and models dialog:** set provider keys and models and the active provider from the page (`core/settings_service.py`). Key fields are write-only; the page only ever receives masked hints, and key values are never logged.
*   **Mail badge** and a **quit notice** when Flexie shuts down.
*   **Launcher helper:** `interface/launcher.py` starts, reuses and stops the web bridge for "open web ui" / "open vision mode" and is stopped on "exit". It also contains an optional tray + global-hotkey class (default Ctrl+Alt+F, `FLEXIE_HOTKEY`) that `main.py` does **not** start, because the Qt HUD already has its own tray and Ctrl+F hotkey.

## 🧠 2. Intelligent Brain & Core Logic
**Category: Reasoning & NLP**
*   **Multi-LLM Fallback:** Local-first (Ollama, when it is running; `FLEXIE_LOCAL_FIRST=0` skips it), then **Groq → OpenAI → DeepSeek → Mistral → Gemini → Anthropic**. Only providers with a configured key are tried; each client uses `max_retries=0` and a hard timeout, so a failing provider costs one timeout, not several.
*   **Rate-limit aware:** Groq limits are per model, so a rate-limited main model falls through to its sibling models (`GROQ_FALLBACK_MODELS`, default `openai/gpt-oss-120b,qwen/qwen3.8-27b`). Gemini defaults to `gemini-flash-latest` and, if a model name has been retired or is overloaded, tries `gemini-3.8-flash` (Gemini rejects request deadlines under 10 s, so its timeout is clamped to at least 15 s).
*   **Honest failure handling:** If every provider fails, a plain question gets a DuckDuckGo web-search answer. That fallback is **never** used for image questions, for JSON/planning calls, or for code generation (`core/llm_failure.py` recognises these fallback messages so they cannot be saved as a source file or parsed as data).
*   **Circuit breaker:** A provider that keeps failing is skipped for a cool-down, then given one trial request.
*   **Persistent SQLite Memory:** Remembers your history, URLs, and previous queries across restarts. Secrets are scrubbed before anything is stored, conversation memories expire (14 days), the stores are pruned hourly, and "forget" reaches every store (chat, facts, vector memory, activity, wiki).
*   **Robust Intent Routing:** A high-speed regex and keyword-based router (96 intents, ~200 natural-language overrides, cached typo correction, ~0.5 ms median) that classifies commands (Search, Apps, Media, Calc …) before processing. The model is only used for open-ended requests.
*   **Wake word:** After start-up Flexie sleeps until it hears "Flexie" (or another wake word). If it hears speech while asleep it logs it and, at most once a minute, says "I'm asleep. Say 'Flexie' first, then your command." instead of silently ignoring you.
*   **Dual Response (Show & Tell):** Every query results in both a spoken response (TTS) and a Markdown-rendered visual result in the dashboard.

## 🪞 3. Self-Awareness (live, not guessed)
**Category: Introspection** (`core/self_model.py`)
*   **Answers from real state:** "what model are you using", "what did you just do", "why did that fail", "are you listening", "what are you doing", "what do you remember about me", "what tools do you have", "what can't you do", "can you see my screen", "who made you". These never go to a language model, so they cannot be invented ("I'm GPT-4").
*   **Command log:** Every user command is recorded with its intent, whether it worked (a handler that says "I couldn't find…" counts as not working), the error text and what Flexie told you. "Why did that fail" reports the last recorded failure.
*   **Grounded persona:** The system prompt tells the model it is Flexie, not ChatGPT, and must not claim actions it was not told happened.

## 🌐 4. Professional Web Automation
**Category: Browser Interaction**
*   **Stealth Playwright Integration:** Uses advanced arguments to bypass bot detection on major platforms.
*   **Select & Search (CLIP):** A dedicated button to analyze or summarize whatever is currently in your system clipboard.
*   **YouTube Master:** Auto-skips ads and provides voice/click control for playback.
*   **Gmail Integration:** Scans and reads out unread emails from your connected account.
*   **Captcha Awareness:** Detects bot-checks and pauses execution to handover control to the user.
*   **AI-Powered Summaries:** Instead of just opening a search tab, Flexie provides a concise AI summary of the top results directly in the UI.
*   **"Open Chrome and search for X":** treated as one request — the Google search is opened straight in that browser (no research essay read aloud). "Close the chrome that you opened" / "close all chromes" resolve to the app name `chrome`.
*   **Image download:** "download 5 images of cats" searches the web (DuckDuckGo images, safe-search on) and saves them to a new folder under `Downloads\Flexie Images`; "download images from <page URL>" takes the pictures from that page (`engines/image_downloader.py`). Only public http(s) addresses are allowed (localhost, LAN, link-local and `file:` are refused, redirects are re-checked), each file must be a real image under 15 MB, and at most 20 are saved per request. It cannot read the tab you are viewing in your own Chrome.

## 👁️ 5. Vision & Debugging
**Category: Screen Intelligence**
*   **Screenshot:** "take a screenshot" saves it to the `captures/` folder and tells you the file name and location.
*   **Screen analysis:** "describe / summarize / check / analyze my screen" sends a (downscaled) screenshot to a vision-capable model — **Gemini only**; text-only models never receive the image and are not asked. The wording of your request is passed on ("summarize" gives a short summary; "check my screen, the tab says wrong" answers that). If Gemini is unavailable Flexie says so and reads the on-screen text with OCR (Tesseract) instead of guessing.
*   **Read my screen:** reads the on-screen text (OCR) directly.
*   **Visual Debugging:** Can identify error messages on your desktop and suggest fixes (needs the vision model).

## 🔮 6. Vision Mode (hand-gesture orb)
**Category: Interface**
*   **"Open vision mode"** (also start/launch/run vision mode, "start the orb") starts the web bridge if needed and opens `http://localhost:8766/#orb`; an already-open dashboard switches to the Orb tab. **"Close vision mode"** closes the panel. There is no Node.js step and no separate server: the orb is a committed bundle (`interface/static/orb.js`, built from `interface/orb/`; it was ported from the standalone `vision/` Next.js app, which Flexie no longer launches).
*   The orb shares the dashboard's origin and authenticated WebSocket, so it reflects Flexie's live state (idle, listening, thinking, speaking).
*   Press **G** (or the button) to turn hand gestures on (pinch to spin, two-hand pinch to zoom). Gestures are **off by default**: only then does the page load MediaPipe (from `cdn.jsdelivr.net`, model from `storage.googleapis.com`; the page's CSP allows only those hosts for this) and ask for camera access, so gestures need internet access.
*   Not yet exercised in a real browser: the orb rendering, the modals and camera hand tracking were checked with code tests, jsdom and a live bridge round-trip, not by eye.

---

## 🛑 Limitations
*   **Windows-Centric:** The Qt HUD's Ctrl+F hotkey (`ctypes`), brightness control, and process management rely on Windows APIs (`ctypes`, `win32`).
*   **PyQt6 licence:** the HUD depends on PyQt6 (GPL v3 / commercial) while the project is MIT; this is an open decision.
*   **API Dependency:** High-quality reasoning requires a 3rd party API key (Groq/Gemini). While Ollama is supported for offline use, performance scales with hardware.
*   **Manual Captcha:** Flexie is designed to be a "Human-in-the-loop" agent; she detects captchas but does not solve them (safeguard).
*   **Browser Lock:** Some features work best with Chrome (Playwright's default targets). Flexie cannot read or act on the tab you are viewing in your own Chrome window; it opens pages/searches or works on a URL you give it.
*   **Vision depends on Gemini:** no other configured provider receives images. When Gemini is overloaded (HTTP 503) or has no key, screen descriptions are unavailable and OCR text is read instead.
*   **Speech recognition:** the offline fallbacks need `ffmpeg` (Whisper) or a local Vosk model; without them a failed online pass is not retried offline, so noisy audio is simply dropped.
*   **Wake word required:** after start-up Flexie only acts on speech that includes the wake word until it has been woken.

## ⚠️ Known Failure Points
*   **Selector Fragility:** If a website (e.g., Gmail) significantly changes its HTML layout, specific automation scripts may fail until updated.
*   **API Rate Limits:** Usage on free tiers (especially Groq) can lead to temporary "Rate Limit Reached" errors.
*   **STT Noise:** In extremely loud environments, the Speech-to-Text engine may fail to parse subtle wake-word triggers.
*   **Port Conflicts:** Flexie needs these free on localhost: UDP `9887` (orchestrator command input) and `9888` (web bridge updates), WebSocket `8765`, HTTP `8766` (dashboard and `/static`) and the REST/SSE API `8768` (browser extension; `main.py` disables the API and logs an error if the port is taken). UDP `9886` is the Qt HUD's port (the HUD registers it and the orchestrator always sends it updates); the web bridge has its own port `9888`. Every UDP datagram, in both directions, carries the per-run `FLEXIE_UDP_TOKEN` (see `utils/udp_auth.py`; unsigned UI-bound datagrams are accepted only with `FLEXIE_ALLOW_UNSIGNED_UI=1`); `main.py` also writes the token to `.flexie_udp_token` so a bridge started by hand authenticates. Open the dashboard at `http://localhost:8766/` (the bridge page where the token is injected) — opening `web_ui.html` from disk can never authenticate. The bridge answers HTTP 421 for any Host other than localhost/127.0.0.1, closes WebSockets from any other Origin (so a page on another port, such as the old orb on `localhost:3000`, is rejected with close code 4003), and serves `/static/<file>` only for flat file names with known extensions.

## 🛡️ Safety behaviour you will notice
*   **Confirmation before risk:** destructive, financial, outbound-message and publish actions are detected per sentence/clause ("what time is it. delete everything" still asks) and need a spoken "confirm" (a short pure approval such as "yes" or "do it"; "ok but first delete everything" is not approval). Approvals have an id, expire (120 s pending, 60 s once granted) and apply to that one action only.
*   **Web/email/MCP content is untrusted:** after such content enters a turn, effectful tools (click, fill, open, write) need approval until your next command.
*   **Clipboard privacy:** clipboard history is opt-in (`FLEXIE_CLIPBOARD_MONITOR=1`) and never stores OTPs, card numbers or token-looking text.

## 🔍 Edge Cases
*   **Ctrl+F is global while the HUD runs:** the Qt HUD registers Ctrl+F as a global hotkey (it opens the spotlight popup), so other apps lose Ctrl+F (Find). If another app already owns it, the HUD simply runs without the hotkey.
*   **No HUD window or tray:** without a desktop session, or if PyQt6 is missing, the UI process exits and Flexie keeps running headless; say "open web ui" (or use the REST API) instead.
*   **No blank Chrome at start-up:** Flexie's Playwright browser starts lazily, the first time something needs it. Set `FLEXIE_PREWARM_BROWSER=1` to pre-start it (it opens a visible blank Chromium window) for a faster first browser command.
*   **Several dashboards open:** every open dashboard receives the same state updates; "open vision mode" opens an extra tab and also switches an open dashboard to its Orb tab.
*   **Math Complexity:** While Flexie handles basic arithmetic and symbolic math, extremely high-order differential equations may require the "Browser Search" intent for full accuracy.

---
*Created for the Flexiee 2.0 Feature Documentation Suite.*

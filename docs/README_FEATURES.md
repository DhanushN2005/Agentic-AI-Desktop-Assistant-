# Flexie 2.0: Comprehensive Feature & Limitation Guide

Flexie 2.0 is an advanced desktop AI assistant built for high-performance automation and intelligent interaction. This document outlines every capability, current constraint, and known edge case of the system.

---

## 🎨 1. UI/UX & Aesthetics (Next-Gen HUD)
**Category: Interface & Visualization**
*   **Glassmorphism Dashboard:** A premium, semi-transparent frosted glass UI with real-time background blur.
*   **Minimalist "Copilot" Mode:** Triggered via `Ctrl+F`, this mode collapses the entire dashboard into a sleek, adaptive search bar and answer area.
*   **Adaptive Window Reflow:** The popup dynamically grows or shrinks its height to perfectly fit AI responses, ensuring no wasted screen space.
*   **Reactive Waveform:** A real-time visualizer that moves in sync with Flexie’s voice processing states.
*   **System Metrics HUD:** Real-time tracking of CPU, RAM, and Battery usage with smooth custom progress bars.
*   **Hardware Control Sliders:** Direct integrated control over System Volume and Screen Brightness.
*   **AI Core Switcher:** Hot-swappable personality modes (Professional, Hacker, Focus, etc.).

## 🧠 2. Intelligent Brain & Core Logic
**Category: Reasoning & NLP**
*   **Multi-LLM Fallback:** Local-first (Ollama, when it is running; `FLEXIE_LOCAL_FIRST=0` skips it), then **Groq → OpenAI → DeepSeek → Mistral → Gemini → Anthropic**. Only providers with a configured key are tried; each client uses `max_retries=0` and a hard timeout, so a failing provider costs one timeout, not several.
*   **Rate-limit aware:** Groq limits are per model, so a rate-limited main model falls through to its sibling models (`GROQ_FALLBACK_MODELS`, default `openai/gpt-oss-120b,qwen/qwen3.8-27b`). Gemini defaults to `gemini-flash-latest` and, if a model name has been retired or is overloaded, tries `gemini-3.8-flash` (Gemini rejects request deadlines under 10 s, so its timeout is clamped to at least 15 s).
*   **Honest failure handling:** If every provider fails, a plain question gets a DuckDuckGo web-search answer. That fallback is **never** used for image questions, for JSON/planning calls, or for code generation (`core/llm_failure.py` recognises these fallback messages so they cannot be saved as a source file or parsed as data).
*   **Circuit breaker:** A provider that keeps failing is skipped for a cool-down, then given one trial request.
*   **Persistent SQLite Memory:** Remembers your history, URLs, and previous queries across restarts. Secrets are scrubbed before anything is stored, conversation memories expire (14 days), the stores are pruned hourly, and "forget" reaches every store (chat, facts, vector memory, activity, wiki).
*   **Robust Intent Routing:** A high-speed regex and keyword-based router (96 intents, ~200 natural-language overrides, cached typo correction, ~0.5 ms median) that classifies commands (Search, Apps, Media, Calc …) before processing. The model is only used for open-ended requests.
*   **Wake word:** After start-up Flexie sleeps until it hears "Flexie" (or another wake word). If it hears speech while asleep it logs it and, at most once a minute, says "I'm asleep. Say 'Flexie' first, then your command." instead of silently ignoring you.
*   **Dual Response (Show & Tell):** Every query results in both a spoken response (TTS) and a Markdown-rendered visual result in the popup.

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
*   **"Open vision mode"** (also start/launch/run vision mode, "start the orb") launches the separate **ULTRON Orb UI** in `vision/` (Next.js + Three.js + MediaPipe) and opens it in your browser; **"close vision mode"** stops it (`engines/vision_mode.py`). The first launch runs `npm ci` (a few minutes, needs Node.js/npm); the dev server uses the first free port from 3000.
*   Press **G** in the page and allow camera access to turn hand gestures on (pinch to spin, two-hand pinch to zoom). The orb tries to connect to the backend WebSocket (`ws://127.0.0.1:8765`), but the bridge only accepts the dashboard origin and requires an `AUTH:` token, so today the orb runs as a standalone visual.

---

## 🛑 Limitations
*   **Windows-Centric:** Global hotkeys (`Ctrl+F`), brightness control, and process management currently rely on Windows API (`ctypes`, `win32`).
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
*   **Port Conflicts:** Flexie needs these free on localhost: UDP `9886` (Qt UI, UI-bound updates), `9887` (orchestrator command input), `9888` (web bridge updates), WebSocket `8765`, HTTP `8766` (dashboard) and the REST/SSE API `8768` (browser extension; `main.py` disables the API and logs an error if the port is taken). Every UDP datagram, in both directions, carries the per-run `FLEXIE_UDP_TOKEN` (see `utils/udp_auth.py`; unsigned UI-bound datagrams are accepted only with `FLEXIE_ALLOW_UNSIGNED_UI=1`); `main.py` also writes the token to `.flexie_udp_token` so a bridge/UI started by hand authenticates. Open the dashboard at `http://localhost:8766/` (the bridge page where the token is injected) — opening `web_ui.html` from disk can never authenticate. The bridge answers HTTP 421 for any Host other than localhost/127.0.0.1 and closes WebSockets from any other Origin.

## 🛡️ Safety behaviour you will notice
*   **Confirmation before risk:** destructive, financial, outbound-message and publish actions are detected per sentence/clause ("what time is it. delete everything" still asks) and need a spoken "confirm" (a short pure approval such as "yes" or "do it"; "ok but first delete everything" is not approval). Approvals have an id, expire (120 s pending, 60 s once granted) and apply to that one action only.
*   **Web/email/MCP content is untrusted:** after such content enters a turn, effectful tools (click, fill, open, write) need approval until your next command.
*   **Clipboard privacy:** clipboard history is opt-in (`FLEXIE_CLIPBOARD_MONITOR=1`) and never stores OTPs, card numbers or token-looking text.

## 🔍 Edge Cases
*   **Empty Clipboard:** Clicking `CLIP` when the clipboard has no text will trigger a "Clipboard Empty" warning instead of an analysis.
*   **Concurrent Hotkeys:** If a system's native `Ctrl+F` is heavily intercepted by another high-priority app (like some full-screen games), the Flexie popup may be delayed.
*   **Dual Monitors:** The popup currently spawns relative to the orb's position; on multi-monitor setups, ensuring the orb is on the primary screen is recommended for consistent spawning.
*   **Math Complexity:** While Flexie handles basic arithmetic and symbolic math, extremely high-order differential equations may require the "Browser Search" intent for full accuracy.

---
*Created for the Flexiee 2.0 Feature Documentation Suite.*

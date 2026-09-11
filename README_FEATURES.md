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
*   **Multi-LLM Fallback:** Graceful failover between **Groq**, **Gemini**, and local **Ollama** ensures the assistant is always online.
*   **Self-Correction Logic:** If an LLM fails, Flexie automatically resorts to a DuckDuckGo web search to answer your question.
*   **Persistent SQLite Memory:** Remembers your history, URLs, and previous queries across restarts.
*   **Robust Intent Routing:** A high-speed regex and keyword-based router that classifies commands (Search, Apps, Media, Calc) before processing.
*   **Dual Response (Show & Tell):** Every query results in both a spoken response (TTS) and a Markdown-rendered visual result in the popup.

## 🌐 3. Professional Web Automation
**Category: Browser Interaction**
*   **Stealth Playwright Integration:** Uses advanced arguments to bypass bot detection on major platforms.
*   **Select & Search (CLIP):** A dedicated button to analyze or summarize whatever is currently in your system clipboard.
*   **YouTube Master:** Auto-skips ads and provides voice/click control for playback.
*   **Gmail Integration:** Scans and reads out unread emails from your connected account.
*   **Captcha Awareness:** Detects bot-checks and pauses execution to handover control to the user.
*   **AI-Powered Summaries:** Instead of just opening a search tab, Flexie provides a concise AI summary of the top results directly in the UI.

## 👁️ 4. Vision & Debugging
**Category: Screen Intelligence**
*   **Instant Screen Snap:** Captures a desktop screenshot and analyzes it using Gemini Vision to explain what's on your screen.
*   **Visual Debugging:** Can identify error messages on your desktop and suggest fixes.

---

## 🛑 Limitations
*   **Windows-Centric:** Global hotkeys (`Ctrl+F`), brightness control, and process management currently rely on Windows API (`ctypes`, `win32`).
*   **API Dependency:** High-quality reasoning requires a 3rd party API key (Groq/Gemini). While Ollama is supported for offline use, performance scales with hardware.
*   **Manual Captcha:** Flexie is designed to be a "Human-in-the-loop" agent; she detects captchas but does not solve them (safeguard).
*   **Browser Lock:** Some features work best with Chrome (Playwright's default targets).

## ⚠️ Known Failure Points
*   **Selector Fragility:** If a website (e.g., Gmail) significantly changes its HTML layout, specific automation scripts may fail until updated.
*   **API Rate Limits:** Usage on free tiers (especially Groq) can lead to temporary "Rate Limit Reached" errors.
*   **STT Noise:** In extremely loud environments, the Speech-to-Text engine may fail to parse subtle wake-word triggers.
*   **Port Conflicts:** The UDP-based UI-to-Orchestrator communication requires port `10000` to be free.

## 🔍 Edge Cases
*   **Empty Clipboard:** Clicking `CLIP` when the clipboard has no text will trigger a "Clipboard Empty" warning instead of an analysis.
*   **Concurrent Hotkeys:** If a system's native `Ctrl+F` is heavily intercepted by another high-priority app (like some full-screen games), the Flexie popup may be delayed.
*   **Dual Monitors:** The popup currently spawns relative to the orb's position; on multi-monitor setups, ensuring the orb is on the primary screen is recommended for consistent spawning.
*   **Math Complexity:** While Flexie handles basic arithmetic and symbolic math, extremely high-order differential equations may require the "Browser Search" intent for full accuracy.

---
*Created for the Flexiee 2.0 Feature Documentation Suite.*

import os
import json
import time
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging


# ---------------------------------------------------------------------------
# Static self-knowledge: Flexie's single source of truth for "what can I do",
# "what can't I do", its sub-agents, modes, and internal sub-systems.
# ---------------------------------------------------------------------------
CAPABILITY_GROUPS = [
    ("System & PC",
     "control apps, volume, brightness, media keys, screen snapping, power (with auth), "
     "and system status like CPU, RAM, battery."),
    ("Browser & Web",
     "open websites, search the web, drive Chrome with clicks, tabs, scrolls and forms, "
     "control YouTube (play, skip ads, pause, captions), and host a live web dashboard."),
    ("Coding & Dev",
     "write, generate, debug and run code, explain repositories, auto-build apps, "
     "search your codebase, run safe terminal commands, and scaffold projects."),
    ("Vision & Screen",
     "take screenshots, analyze or describe your screen, read text from screen (OCR), "
     "debug an error visible on screen, and capture photos from your webcam."),
    ("Voice & Speech",
     "listen via mic and reply by voice, adjust speech rate/language, and run "
     "voice-controlled hands-free gestures from the web UI."),
    ("Files & Email & Messaging",
     "open, rename, move, delete and organize files and folders, read and summarize PDFs, "
     "check and send email, message on WhatsApp."),
    ("Information",
     "answer questions with AI, web research with summaries, weather, news, time, "
     "definitions, translations, Wikipedia, and local file knowledge search."),
    ("Memory & Notes",
     "remember facts about you, keep chat history and notes, recall them on demand, "
     "and learn your preferences over time."),
    ("Productivity & Automation",
     "set reminders, alarms, timers, notifications and pomodoros, run daily briefings, "
     "auto-save files, organize your desktop, and schedule recurring automations."),
    ("Utility Tools",
     "calculator, unit conversion, QR codes, passwords, dictionaries, UUIDs, JSON "
     "formatting, hashing, text tools, colors, tip splitting, BMI, age, image generation, "
     "quotes and jokes."),
]

# Things Flexie explicitly CANNOT do (honest limitation awareness).
LIMITATIONS = [
    "I am software on your PC: I cannot physically touch hardware, move in the real world, or repair physical devices.",
    "I need internet for most AI brains, web search, weather, news, email, and image generation.",
    "I need your microphone allowed to hear you and your camera allowed to see you.",
    "I cannot unlock your phone, password-protected files, or accounts that require 2-factor verification.",
    "I cannot read your mind — you must speak, type, or gesture a command.",
    "I refuse destructive or unsafe actions: restricted words are filtered and power/shutdown commands require your authorization phrase.",
    "I am desktop-only: mobile apps, and cloud-hosted deployments are out of scope.",
]

# Internal sub-agents / specialized executors Flexie can delegate to.
SUB_AGENTS = {
    "Browser Agent": "drives Chrome and the web: clicking, filling forms, tabs, extracting page content and navigating.",
    "Coding Agent": "writes and edits code, runs safe terminal commands, and builds apps in your workspace.",
    "Memory Agent": "stores, recalls and searches long-term facts, notes and conversation history.",
    "Verification Agent": "double-checks completed tasks against expected outcomes to catch failures.",
    "SDD Engineer": "turns a product idea into a structured build plan and generated task graph.",
    "Goal Planner": "breaks big or ambiguous requests into step-by-step plans I execute in order.",
    "Automation Scheduler": "runs recurring jobs and rules on a schedule (daily, hourly) in the background.",
}

# UI / behavior modes.
MODE_MAP = {
    "professional": "default balanced mode — standard responses and confirmations.",
    "developer": "optimized for coding, debugging and technical work.",
    "hacker": "silent autonomous mode — executes via tool calls without chatter.",
    "minimal": "distraction-free, minimal UI and replies.",
    "focus": "focus-mode UI that reduces interruptions.",
}

# Internal sub-systems (engines/components) — how Flexie is built.
SYSTEM_MAP = {
    "Brain": "multi-provider AI core (Groq, OpenAI, DeepSeek, Gemini, Anthropic, Mistral, plus local Ollama fallback).",
    "Router & Orchestrator": "turns natural language into intents, plans multi-step goals, and guards execution.",
    "Memory": "chat history, long-term facts, vector search and preference learning.",
    "Voice Interface": "speech input + TTS output, wake word control.",
    "Vision Engine": "screenshots, screen analysis, gesture hand tracking from the web UI.",
    "Browser Engine": "Playwright-driven Chrome automation and YouTube ad-skipping.",
    "Files & Developer": "file management and repository/code tooling.",
    "Knowledge & Search": "local file indexing and web research.",
    "Web Dashboard": "live web UI (bridge on port 8766), WebSocket 8765, UDP 9887.",
    "Music & Email & Weather & News": "media playback, mail, forecast and headlines engines.",
}

# TTS-safe concise phrasing for each section (spoken aloud).
_CAPABILITY_SPEECH = (
    "I control your system, apps, browser, YouTube and music; I write and run code, "
    "analyze projects, and can see your screen and webcam. I handle email, reminders, "
    "alarms, weather, news, notes and memory, plus 30-plus tools like calculators, "
    "QR codes, image generation, translation and dictionaries."
)

_LIMITATION_SPEECH = (
    "I am desktop-only software: I need your mic, camera, and internet for most AI and "
    "email features, and I can't touch physical hardware or unlock password-protected "
    "accounts. I filter unsafe words and require authorization for destructive power actions."
)

_SUB_AGENT_SPEECH = (
    "Sub-agents handle heavy lifting: the Browser agent drives Chrome and the web UI, "
    "the Coding agent writes and edits code, the Memory agent stores facts about you, "
    "the Verification agent double-checks my work, SDD Engineer scaffolds new projects, "
    "and Goal Planner breaks big tasks into plans I execute."
)

_MODE_SPEECH = (
    "I have five modes. Professional is the default balanced mode. Developer is "
    "tuned for coding and debugging. Hacker runs silently and autonomously. "
    "Minimal keeps the UI and replies distraction-free. Focus reduces "
    "interruptions for deep work."
)

_SYSTEM_SPEECH = (
    "I am built in Python: a multi-provider AI Brain, a router and orchestrator, memory, "
    "voice, vision, a browser engine, files and developer tools, plus a live web "
    "dashboard on port 8766 with WebSocket 8765."
)


class SelfAwareness:
    """Self-awareness system: tracks own state, capabilities, history, and personality."""

    def __init__(self, db_path: str = "flexie_awareness.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._start_time = datetime.now()
        self._commands_processed = 0
        self._errors_encountered = 0
        self._features_used: Dict[str, int] = {}
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    command TEXT,
                    intent TEXT,
                    response TEXT,
                    success INTEGER,
                    duration_ms REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS personality (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact TEXT UNIQUE,
                    category TEXT,
                    confidence REAL DEFAULT 1.0,
                    learned_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def log_command(self, command: str, intent: str, response: str, success: bool, duration_ms: float):
        """Log a command execution for self-awareness."""
        self._commands_processed += 1
        self._features_used[intent] = self._features_used.get(intent, 0) + 1
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT INTO session_log (timestamp, command, intent, response, success, duration_ms) VALUES (?,?,?,?,?,?)",
                (time.time(), command, intent, response[:500], 1 if success else 0, duration_ms)
            )
            conn.commit()
            conn.close()

    def learn_fact(self, fact: str, category: str = "general", confidence: float = 1.0):
        """Learn a new fact about the user or world."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO user_facts (fact, category, confidence, learned_at) VALUES (?,?,?,?)",
                    (fact, category, confidence, time.time())
                )
                conn.commit()
            except Exception as _e:
                logging.debug("[engines/self_awareness.py:78] Swallowed exception: %s: %s", type(_e).__name__, _e)
                pass
            conn.close()

    def recall_facts(self, category: Optional[str] = None, limit: int = 10) -> List[str]:
        """Recall learned facts."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            if category:
                rows = conn.execute(
                    "SELECT fact FROM user_facts WHERE category=? ORDER BY learned_at DESC LIMIT ?",
                    (category, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fact FROM user_facts ORDER BY learned_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()
        return [r[0] for r in rows]

    def get_self_info(self) -> str:
        """Return self-awareness information."""
        uptime = datetime.now() - self._start_time
        hours = int(uptime.total_seconds() // 3600)
        mins = int((uptime.total_seconds() % 3600) // 60)

        top_features = sorted(self._features_used.items(), key=lambda x: x[1], reverse=True)[:5]
        features_str = ", ".join(f"{k}({v})" for k, v in top_features) if top_features else "None yet"

        facts = self.recall_facts(limit=5)
        facts_str = "; ".join(facts) if facts else "No facts learned yet."

        return (
            f"I am Flexie, your AI desktop assistant. "
            f"Uptime: {hours}h {mins}m. "
            f"Commands processed: {self._commands_processed}. "
            f"Top features: {features_str}. "
            f"What I know: {facts_str}"
        )

    def get_stats(self) -> str:
        """Return detailed statistics."""
        uptime = datetime.now() - self._start_time
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            total = conn.execute("SELECT COUNT(*) FROM session_log").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM session_log WHERE success=1").fetchone()[0]
            avg_duration = conn.execute("SELECT AVG(duration_ms) FROM session_log").fetchone()[0] or 0
            facts_count = conn.execute("SELECT COUNT(*) FROM user_facts").fetchone()[0]
            conn.close()

        rate = (success / total * 100) if total > 0 else 0
        return (
            f"Stats: {total} total commands, {success} successful ({rate:.0f}% success rate). "
            f"Average response time: {avg_duration:.0f}ms. "
            f"Facts learned: {facts_count}. "
            f"Uptime: {int(uptime.total_seconds() // 3600)}h {int((uptime.total_seconds() % 3600) // 60)}m."
        )

    def get_personality(self) -> str:
        """Return personality traits."""
        return (
            "I am Flexie, a helpful and efficient AI assistant. "
            "I am concise, direct, and action-oriented. "
            "I learn from our conversations and remember important details about you. "
            "I am always improving and adapting to your preferences."
        )

    # --- Full self-knowledge queries ------------------------------------

    def get_capabilities(self) -> str:
        """Return a spoken summary of what Flexie can do."""
        return _CAPABILITY_SPEECH

    def get_capabilities_detail(self) -> str:
        """Return structured capability groups (sections separated by newlines)."""
        return "\n".join(f"{name}: {desc}" for name, desc in CAPABILITY_GROUPS)

    def get_limitations(self) -> str:
        """Return spoken limitations of Flexie."""
        return _LIMITATION_SPEECH

    def get_limitations_detail(self) -> str:
        """Return structured limitation list."""
        return "\n".join(f"- {lim}" for lim in LIMITATIONS)

    def get_sub_agents(self) -> str:
        """Return spoken summary of internal sub-agents."""
        return _SUB_AGENT_SPEECH

    def get_sub_agents_detail(self) -> str:
        """Return structured sub-agent descriptions."""
        return "\n".join(f"{name}: {desc}" for name, desc in SUB_AGENTS.items())

    def get_modes(self) -> str:
        """Return spoken summary of the available modes."""
        return _MODE_SPEECH

    def get_modes_detail(self) -> str:
        """Return structured mode descriptions."""
        return "\n".join(f"{name}: {desc}" for name, desc in MODE_MAP.items())

    def get_system_map(self) -> str:
        """Return spoken summary of internal sub-systems."""
        return _SYSTEM_SPEECH

    def get_system_map_detail(self) -> str:
        """Return structured sub-system descriptions."""
        return "\n".join(f"{name}: {desc}" for name, desc in SYSTEM_MAP.items())

    def get_full_knowledge(self) -> str:
        """Return the complete structured self-knowledge profile (for logs/UI)."""
        parts = [
            "CAPABILITIES",
            self.get_capabilities_detail(),
            "\nLIMITATIONS",
            self.get_limitations_detail(),
            "\nSUB-AGENTS",
            self.get_sub_agents_detail(),
            "\nMODES",
            self.get_modes_detail(),
            "\nSUB-SYSTEMS",
            self.get_system_map_detail(),
        ]
        return "\n".join(parts)

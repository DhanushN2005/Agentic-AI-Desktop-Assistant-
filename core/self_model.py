"""Flexie's live model of itself.

Every answer here is built from real, current state (what ran, what failed and why, which
models and tools are configured, what is remembered, whether it is awake) - never from a
language model's guess. Questions like "what model are you using?" or "why did that fail?"
used to be answered by the LLM, which invented answers ("I'm built on GPT-4").
"""
from __future__ import annotations

import re
import time
from collections import deque

from utils.config import Config

# (regex, handler-name) in priority order. Matched against the lower-cased question.
_QUESTIONS: list[tuple[str, str]] = [
    (r"\bwhat\s+(?:model|llm|ai|brain|provider|engine)\b.*\b(?:you|your)\b|\b(?:which|what)\s+(?:model|llm)\b.*\b(?:you|your)\b|\bare\s+you\s+(?:gpt|chatgpt|openai|gemini|llama)\b|\bwho\s+(?:made|built|created|trained)\s+you\b", "model"),
    (r"\bwhy\s+(?:did|didn'?t|does|is|was)\b.*\b(?:that|it|this)\b.*\b(?:fail|failed|work|stop|wrong|error)|\bwhat\s+(?:went\s+wrong|was\s+the\s+(?:error|problem|issue))\b|\bwhy\s+(?:did|didn'?t)\s+(?:that|it)\b|\bwhat\s+failed\b", "why_failed"),
    (r"\bwhat\s+(?:did|have)\s+you\s+(?:just\s+)?(?:do|done|been\s+doing)\b|\bwhat\s+was\s+that\b|\b(?:recent|last)\s+(?:commands?|actions?|activity)\b|\bdid\s+(?:that|it)\s+work\b", "recent"),
    (r"\bare\s+you\s+(?:listening|awake|asleep|sleeping|online|connected|there|ready|busy|working)\b|\bcan\s+you\s+hear\s+me\b", "state"),
    (r"\bwhat\s+are\s+you\s+(?:doing|up\s+to|working\s+on)\b|\bwhat'?s\s+your\s+(?:status|state)\b|\bstatus\s+report\b|\bhow\s+are\s+you\s+(?:running|performing)\b", "state"),
    (r"\bwhat\s+do\s+you\s+(?:remember|know)\s+about\s+me\b|\bwhat\s+have\s+you\s+(?:learned|learnt|remembered)\b|\bwhat\s+do\s+you\s+remember\b", "memory"),
    (r"\bwhat\s+(?:tools|abilities|skills|features|commands)\s+do\s+you\s+have\b|\bhow\s+many\s+(?:tools|intents|commands|skills)\b|\bwhat\s+(?:tools|apps)\s+can\s+you\s+use\b", "tools"),
    (r"\bwhat\s+(?:can'?t|cannot)\s+you\s+do\b|\byour\s+limit(?:ation)?s?\b|\bwhat\s+are\s+you\s+(?:bad|not\s+good)\s+at\b|\bwhat\s+don'?t\s+you\s+(?:know|support)\b", "limits"),
    (r"\bcan\s+you\s+(?:see|look\s+at)\s+(?:my\s+)?(?:screen|desktop)\b|\bcan\s+you\s+(?:really\s+)?see\b", "vision"),
]
_COMPILED = [(re.compile(p), name) for p, name in _QUESTIONS]
SELF_QUESTION_REGEX = "|".join(f"(?:{p})" for p, _ in _QUESTIONS)


def classify(question: str) -> str | None:
    """Which self-question this is (or None)."""
    q = (question or "").lower().strip()
    for rx, name in _COMPILED:
        if rx.search(q):
            return name
    return None


_FAILED_REPLY = re.compile(
    r"^\s*(?:sorry[, ]|i (?:couldn'?t|could not|can'?t|cannot|was unable|am unable|wasn'?t able|didn'?t)\b|"
    r"unable to\b|failed\b|error\b|there was (?:an )?(?:error|problem)|something went wrong|"
    r"no (?:such|matching)\b)|\b(?:did not work|not found|doesn'?t exist|does not exist|couldn'?t find)\b",
    re.IGNORECASE,
)


def reply_looks_failed(reply: str | None) -> bool:
    """True when what Flexie told the user says the task did not work (handlers often return
    success even though they said "I couldn't find ...")."""
    return bool(reply and _FAILED_REPLY.search(reply[:200]))


class CommandLog:
    """Bounded record of what Flexie actually did (command, intent, outcome, error, reply)."""

    def __init__(self, maxlen: int = 30):
        self._items: deque = deque(maxlen=maxlen)

    def add(self, cmd: str, intent: str | None, ok: bool, error: str | None, reply: str | None, ms: float) -> None:
        if ok and reply_looks_failed(reply):
            ok, error = False, error or reply
        self._items.append({
            "cmd": (cmd or "")[:200], "intent": intent or "unknown", "ok": bool(ok),
            "error": (error or "")[:300] or None, "reply": (reply or "")[:300] or None,
            "ms": round(ms), "ts": time.time(),
        })

    def last(self, n: int = 1) -> list[dict]:
        return list(self._items)[-n:]

    def last_failure(self) -> dict | None:
        for item in reversed(self._items):
            if not item["ok"]:
                return item
        return None

    def __len__(self) -> int:
        return len(self._items)


_QUESTIONISH = re.compile(
    r"^(?:what|who|whom|where|when|why|how|which|do you|can you|could you|are you|is |tell me|show me)\b|\?$",
    re.IGNORECASE,
)


def _clean_facts(raw: list) -> list[str]:
    """Drop junk from stored facts: questions the old bug saved as memories, empty values and
    'remember that: remember that' echoes; keep one readable line per fact."""
    out: list[str] = []
    for f in raw:
        t = re.sub(r"^fact:\s*", "", str(f).strip())
        t = re.sub(r"^remember that\s*:?\s*", "", t, flags=re.I).strip(" :")
        if not t or _QUESTIONISH.search(t) or re.fullmatch(r"remember that:?\s*", t, re.I):
            continue
        if ":" in t:
            key, _, val = t.partition(":")
            if not val.strip() or key.strip().lower() == val.strip().lower():
                t = key.strip()
            elif key.strip().lower() in val.strip().lower():
                t = re.sub(r"^remember that\s*", "", val.strip(), flags=re.I)  # "x: remember that x" -> "x"
        if t.lower() not in {x.lower() for x in out} and not any(t.lower() in x.lower() for x in out):
            out.append(t)
    return out


def _ago(ts: float) -> str:
    s = max(0, int(time.time() - ts))
    if s < 10:
        return "just now"
    if s < 90:
        return f"{s} seconds ago"
    if s < 5400:
        return f"{s // 60} minutes ago"
    return f"{s // 3600} hours ago"


class SelfModel:
    """Answers questions about Flexie from live state. ``orch`` is the FlexieOrchestrator."""

    def __init__(self, orch):
        self.orch = orch
        self.started_at = time.time()

    # ---------------------------------------------------------------- facts
    def providers(self) -> dict:
        """Which language-model providers are configured, which one is active, and the model names."""
        brain = getattr(self.orch, "brain", None)
        wait = getattr(brain, "_wait_providers", None)
        if callable(wait):
            wait()  # model clients are built in the background at startup
        has = {
            "groq": bool(getattr(brain, "groq_client", None)),
            "openai": bool(getattr(brain, "openai_client", None)),
            "deepseek": bool(getattr(brain, "deepseek_client", None)),
            "mistral": bool(getattr(brain, "mistral_client", None)),
            "anthropic": bool(getattr(brain, "anthropic_client", None)),
            "gemini": bool(getattr(brain, "_gemini_enabled", False) or getattr(brain, "gemini_new_client", None)),
        }
        models = {
            "groq": getattr(Config, "GROQ_MODEL", ""), "openai": getattr(Config, "OPENAI_MODEL", ""),
            "deepseek": getattr(Config, "DEEPSEEK_MODEL", ""), "mistral": getattr(Config, "MISTRAL_MODEL", ""),
            "anthropic": getattr(Config, "ANTHROPIC_MODEL", ""),
            "gemini": getattr(brain, "_gemini_working_model", None) or getattr(Config, "GEMINI_MODEL", ""),
        }
        try:
            active = brain._active_provider() if brain else "auto"
        except Exception:
            active = "auto"
        return {"configured": [k for k, v in has.items() if v], "models": models, "active": active,
                "local_model": getattr(Config, "OLLAMA_MODEL", ""), "vision": has["gemini"]}

    def intent_count(self) -> int:
        try:
            return len(self.orch.router.intents)
        except Exception:
            return 0

    def tool_names(self) -> list[str]:
        try:
            return sorted(t.name for t in self.orch.tool_registry.list_tools())
        except Exception:
            try:
                return sorted(self.orch.tool_registry._tools)
            except Exception:
                return []

    def state_words(self) -> str:
        o = self.orch
        parts = []
        voice = getattr(o, "voice", None)
        if getattr(o, "is_processing", False):
            parts.append(f"working on: {getattr(o, 'last_command_name', 'a command')!r}")
        elif voice is not None and getattr(voice, "is_speaking", False):
            parts.append("speaking")
        else:
            parts.append("idle and listening" if getattr(o, "active", False) else "asleep until you say my name")
        return parts[0]

    # ---------------------------------------------------------------- answers
    def answer(self, question: str) -> str | None:
        kind = classify(question)
        if kind is None:
            return None
        return getattr(self, f"_a_{kind}")()

    def _a_model(self) -> str:
        p = self.providers()
        if not p["configured"] and not p["local_model"]:
            return ("I'm Flexie, a desktop assistant. Right now I have no language model configured, "
                    "so I can only run the built-in commands.")
        cloud = ", ".join(f"{n} ({p['models'].get(n) or 'default model'})" for n in p["configured"]) or "none"
        local = p["local_model"] or "none"
        active = "I pick whichever is available and fall back if one fails" if p["active"] == "auto" else f"I'm set to use {p['active']}"
        return (f"I'm Flexie, an assistant that runs on this computer. I don't have a single brain of my own: "
                f"my answers come from language models I call. Cloud: {cloud}. Local: {local}. {active}. "
                f"I am not GPT-4 or ChatGPT.")

    def _a_recent(self) -> str:
        log = getattr(self.orch, "command_log", None)
        items = log.last(3) if log else []
        if not items:
            return "I haven't run any commands since I started, so there's nothing to report yet."
        lines = []
        for it in reversed(items):
            status = "worked" if it["ok"] else "did not work"
            reply = f" I told you: {it['reply']!r}." if it["reply"] else ""
            lines.append(f"{_ago(it['ts']).capitalize()} you said {it['cmd']!r}; I handled it as {it['intent']} and it {status}.{reply}")
        return " ".join(lines[:2])

    def _a_why_failed(self) -> str:
        log = getattr(self.orch, "command_log", None)
        last = log.last(1) if log else []
        fail = log.last_failure() if log else None
        if not last:
            return "Nothing has run since I started, so nothing has failed."
        if last[0]["ok"] and not fail:
            return f"Your last command, {last[0]['cmd']!r}, worked, and I have no failures on record."
        target = fail if (fail and not last[0]["ok"]) else fail
        if target is None:
            return f"Your last command, {last[0]['cmd']!r}, worked. I have no failures on record this session."
        why = target["error"] or target["reply"] or "the handler reported failure without a message"
        return (f"The last failure was {target['cmd']!r}, {_ago(target['ts'])}, handled as {target['intent']}. "
                f"What I recorded: {why}")

    def _a_state(self) -> str:
        p = self.providers()
        uptime = int(time.time() - self.started_at)
        up = f"{uptime // 3600}h {(uptime % 3600) // 60}m" if uptime >= 3600 else f"{uptime // 60}m {uptime % 60}s"
        log = getattr(self.orch, "command_log", None)
        n = len(log) if log else 0
        mic = "microphone live" if getattr(getattr(self.orch, "voice", None), "stream", True) else "microphone not open"
        return (f"I'm {self.state_words()}. Up for {up}, {n} command{'s' if n != 1 else ''} handled this session, "
                f"{mic}. Models available: {', '.join(p['configured']) or 'no cloud model'}"
                f"{' plus local ' + p['local_model'] if p['local_model'] else ''}.")

    def _a_memory(self) -> str:
        facts: list[str] = []
        try:
            facts = list(self.orch.awareness.recall_facts(limit=8))
        except Exception:
            pass
        try:
            from core.memory_manager import MemoryCategory
            mm = getattr(self.orch, "memory_manager", None)
            if mm:
                for cat in (MemoryCategory.FACTS, MemoryCategory.PREFERENCES):
                    for e in mm.get_by_category(cat)[:5] if hasattr(mm, "get_by_category") else []:
                        facts.append(f"{e.key}: {e.value}")
        except Exception:
            pass
        facts = _clean_facts(facts)[:8]
        if not facts:
            return (f"I haven't saved any facts about you yet, {getattr(Config, 'USER_NAME', '')}. "
                    "Say 'remember that ...' and I'll keep it.")
        return "Here is what I have saved about you: " + "; ".join(facts) + "."

    def _a_tools(self) -> str:
        tools = self.tool_names()
        n = self.intent_count()
        sample = ", ".join(tools[:8])
        return (f"I understand {n} kinds of commands (apps, media, files, mail, alarms, screen, browser and more) "
                f"and have {len(tools)} registered tools for multi-step tasks"
                f"{': ' + sample + (' and more' if len(tools) > 8 else '') if tools else ''}. "
                "Ask 'what can't you do' for my limits.")

    def _a_limits(self) -> str:
        p = self.providers()
        limits = [
            "I can't see a screen or picture unless a vision model answers" + ("" if p["vision"] else " - and none is configured right now"),
            "I can't read the tab you're looking at in your own Chrome, only open pages and searches or work on a URL you give me",
            "I ask before anything destructive or irreversible, and I filter unsafe requests",
            "My speech recognition can mishear you, so say 'Flexie' first and speak clearly",
            "I can't touch physical hardware or unlock password-protected accounts",
        ]
        return "My real limits: " + "; ".join(limits) + "."

    def _a_vision(self) -> str:
        p = self.providers()
        if p["vision"]:
            return ("Yes, I can look at your screen: I take a screenshot and ask a vision model about it. "
                    "If the model is busy I'll say so and read the text on screen instead.")
        return ("Not right now: I have no vision model configured. I can still take screenshots and read the "
                "text on screen.")

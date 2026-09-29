import os
import logging
import re
import tempfile
from typing import Dict
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'), override=True)

SUPPORTED_PROVIDERS = {
    "groq":      {"env": "GROQ_API_KEY",      "model_env": "GROQ_MODEL",      "label": "Groq",              "placeholder": "gsk_...", "help": "console.groq.com/keys", "prefix": "gsk_", "default_model": "openai/gpt-oss-20b",
                 "models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3-32b", "moonshotai/kimi-k2-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct", "groq/compound", "groq/compound-mini"]},
    "gemini":    {"env": "GEMINI_API_KEY",    "model_env": "GEMINI_MODEL",    "label": "Google Gemini",     "placeholder": "AIza...", "help": "aistudio.google.com/app/apikey", "prefix": "AIza", "default_model": "gemini-2.0-flash",
                 "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro"]},
    "openai":    {"env": "OPENAI_API_KEY",    "model_env": "OPENAI_MODEL",    "label": "OpenAI (GPT)",      "placeholder": "sk-...", "help": "platform.openai.com/api-keys", "prefix": "sk-", "default_model": "gpt-4o-mini",
                 "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-5-mini", "gpt-5", "gpt-4-turbo", "o1-mini", "o3-mini"]},
    "deepseek":  {"env": "DEEPSEEK_API_KEY",  "model_env": "DEEPSEEK_MODEL",  "label": "DeepSeek",          "placeholder": "sk-...", "help": "platform.deepseek.com/api_keys", "prefix": "sk-", "default_model": "deepseek-chat",
                 "models": ["deepseek-chat", "deepseek-reasoner"]},
    "anthropic": {"env": "ANTHROPIC_API_KEY", "model_env": "ANTHROPIC_MODEL", "label": "Anthropic Claude",  "placeholder": "sk-ant-...", "help": "console.anthropic.com/settings/keys", "prefix": "sk-ant-", "default_model": "claude-sonnet-4-20250514",
                 "models": ["claude-sonnet-4-20250514", "claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]},
    "mistral":   {"env": "MISTRAL_API_KEY",   "model_env": "MISTRAL_MODEL",   "label": "Mistral AI",        "placeholder": "xxx...", "help": "console.mistral.ai/api-keys", "prefix": "", "default_model": "mistral-small-latest",
                 "models": ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "open-mistral-7b", "open-mixtral-8x7b"]},
    "cohere":    {"env": "COHERE_API_KEY",    "model_env": "COHERE_MODEL",    "label": "Cohere",            "placeholder": "xxx...", "help": "dashboard.cohere.com/api-keys", "prefix": "", "default_model": "command-r-plus",
                 "models": ["command-r-plus", "command-r", "embed-english-v3.0"]},
    "together":  {"env": "TOGETHER_API_KEY",  "model_env": "TOGETHER_MODEL",  "label": "Together AI",       "placeholder": "xxx...", "help": "api.together.xyz/settings/api-keys", "prefix": "", "default_model": "meta-llama/Llama-3-8b-chat-hf",
                 "models": ["meta-llama/Llama-3-8b-chat-hf", "meta-llama/Llama-3-70b-chat-hf", "mistralai/Mixtral-8x7B-Instruct-v0.1"]},
}

# Self-knowledge: Flexie's honest picture of its own capabilities. Injected
# into the standard brain prompt (SYSTEM_PROMPT_STANDARD) so the model answers
# "what can/can't you do", "what agents do you have" and "what modes" questions
# consistently with the real system. Defined at module scope so the class body
# can reference it during class creation.
SELF_KNOWLEDGE = (
    "SELF-KNOWLEDGE (be honest and stick to this):\n"
    "I control this Windows PC: apps, files, volume, brightness, screen snapping, "
    "power (with authorization), browser/Chrome automation, YouTube, music, camera "
    "and screenshots, screen analysis, and voice. I write, debug and run code, "
    "explain repositories, auto-build apps, and run safe terminal commands.\n"
    "SUB-AGENTS: Browser agent (drives Chrome and the web UI), Coding agent "
    "(writes/edits code), Memory agent (stores facts and notes), Verification agent "
    "(checks completed tasks), SDD Engineer (scaffolds new projects), Goal Planner "
    "(breaks tasks into steps), Automation Scheduler (runs recurring jobs). "
    "I also have a live web dashboard/bridge (ports 8766/8765).\n"
    "MODES (5): professional (default balanced), developer (coding/debugging), "
    "hacker (silent autonomous execution), minimal (distraction-free), "
    "focus (fewer interruptions).\n"
    "LIMITATIONS: I am desktop-only software — I need internet for most AI features, "
    "mic/camera access to hear and see, I cannot touch physical hardware, unlock "
    "password-protected accounts, or run destructive commands without authorization."
)

def _validate_env():
    """Warn if API keys are missing or look leaked."""
    groq = os.getenv("GROQ_API_KEY", "")
    gemini = os.getenv("GEMINI_API_KEY", "")
    if not groq or groq.strip() in ('', '""', "''"):
        logging.warning("Config: GROQ_API_KEY missing - Groq LLM disabled, will fallback to Gemini/Ollama")
    elif len(groq) < 20 or not groq.startswith("gsk_"):
        logging.warning("Config: GROQ_API_KEY looks invalid - should start with gsk_")
    if groq and len(groq) > 20:
        logging.warning("Config: GROQ_API_KEY loaded - ensure .env is gitignored and rotate if leaked")
    if not gemini:
        logging.info("Config: GEMINI_API_KEY not set - Gemini fallback disabled")
    # Log other providers status at debug level
    for pid, meta in SUPPORTED_PROVIDERS.items():
        if pid in ("groq", "gemini"):
            continue
        val = os.getenv(meta["env"], "")
        if val:
            logging.info(f"Config: {meta['env']} set ({meta['label']})")

_validate_env()

def _env_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')

# Explicit allowlist of .env keys that may be written programmatically.
# Custom providers are covered by the bounded *_API_KEY / *_MODEL patterns.
_KNOWN_ENV_KEYS = {
    "ACTIVE_PROVIDER", "OLLAMA_URL", "OLLAMA_MODEL",
    "FLEXIE_EMAIL", "FLEXIE_PASS", "LOG_FILE",
    "FLEXIE_VOICE", "FLEXIE_TTS_MODE",
    "FLEXIE_CONVERSATION_HISTORY_TURNS", "FLEXIE_CONVERSATION_HISTORY_CHARS",
    "FLEXIE_ROUTING_CONTEXT_TURNS", "FLEXIE_LLM_REQUEST_TIMEOUT",
    "FLEXIE_CODE_MAX_TOKENS", "FLEXIE_ARTIFACT_SOURCE_CHARS",
    "FLEXIE_VOICE_LISTEN_TIMEOUT", "FLEXIE_CODE_OUTPUT_DIR",
    "FLEXIE_ARTIFACT_BACKUP_DIR", "FLEXIE_JOB_TOKEN_BUDGET",
    "FLEXIE_OPENAI_BRIDGE_ENABLED", "FLEXIE_OPENAI_BRIDGE_PORT",
    "FLEXIE_CHEAP_FIRST_ENABLED",
}
_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CUSTOM_KEY_RES = (
    re.compile(r"^[A-Z][A-Z0-9_]*_API_KEY$"),
    re.compile(r"^[A-Z][A-Z0-9_]*_MODEL$"),
)


def _is_allowed_env_key(key: str) -> bool:
    if not isinstance(key, str) or not _ENV_KEY_RE.match(key):
        return False
    if key in _KNOWN_ENV_KEYS:
        return True
    for meta in SUPPORTED_PROVIDERS.values():
        if key in (meta.get("env"), meta.get("model_env")):
            return True
    return any(rx.match(key) for rx in _CUSTOM_KEY_RES)


def _is_safe_env_value(value: str) -> bool:
    return isinstance(value, str) and "\n" not in value and "\r" not in value

def _read_env_file() -> dict:
    """Read .env into dict (preserves comments handling)."""
    path = _env_path()
    data = {}
    if not os.path.exists(path):
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as _e:
        logging.debug("[utils/config.py:67] Swallowed exception: %s: %s", type(_e).__name__, _e)
        pass
    return data

def _write_env_file(updates: dict) -> bool:
    """Merge updates into .env file atomically (temp + fsync + os.replace)."""
    # Fail closed: reject unknown keys or multiline values before touching disk.
    for k, v in updates.items():
        if not _is_allowed_env_key(k):
            logging.error(f"Config: refusing to write unknown .env key: {k!r}")
            return False
        if not _is_safe_env_value(v):
            logging.error(f"Config: refusing to write unsafe value for {k!r}")
            return False
    path = _env_path()
    # Read existing lines to preserve structure/comments
    lines = []
    existing_keys = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for l in lines:
                s = l.strip()
                if s and not s.startswith("#") and "=" in s:
                    existing_keys.add(s.split("=", 1)[0].strip())
        except Exception as _e:
            logging.debug("[utils/config.py:85] Swallowed exception: %s: %s", type(_e).__name__, _e)
            lines = []
    # Update existing lines
    new_lines = []
    updated = set()
    for l in lines:
        s = l.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated.add(k)
                continue
        new_lines.append(l)
    # Append new keys
    for k, v in updates.items():
        if k not in updated and k not in existing_keys:
            new_lines.append(f"{k}={v}\n")
    try:
        # Atomic write: temp file in the same folder, fsync, then os.replace.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                                   prefix=".env.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # Reload into process env
        for k, v in updates.items():
            os.environ[k] = v
            # Also update Config class attr if exists
            if hasattr(Config, k):
                setattr(Config, k, v if v else None)
        return True
    except Exception as e:
        logging.error(f"Config: Failed to write .env: {e}")
        return False

def _env_number(name, default, converter):
    try:
        return converter(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default):
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "••••"
    return key[:4] + "•" * (len(key) - 8) + key[-4:]

class Config:
    # Basic Info
    NAME       = "Flexie 2.0"
    USER_NAME  = "Dhanush"
    WAKE_WORDS = ["flexie", "arsis", "wake up", "hello flexie", "hey flexie", "activate"]
    DB_NAME    = "flexie_intelligence.db"
    LOG_FILE   = "flexie_activity.log"
    CONVERSATION_HISTORY_TURNS = _env_number("FLEXIE_CONVERSATION_HISTORY_TURNS", 8, int)
    CONVERSATION_HISTORY_CHARS = _env_number("FLEXIE_CONVERSATION_HISTORY_CHARS", 8000, int)
    ROUTING_CONTEXT_TURNS = _env_number("FLEXIE_ROUTING_CONTEXT_TURNS", 5, int)
    LLM_REQUEST_TIMEOUT = _env_number("FLEXIE_LLM_REQUEST_TIMEOUT", 15.0, float)
    CODE_MAX_TOKENS = _env_number("FLEXIE_CODE_MAX_TOKENS", 4096, int)
    JOB_TOKEN_BUDGET = _env_number("FLEXIE_JOB_TOKEN_BUDGET", 50000, int)
    ARTIFACT_SOURCE_CHARS = _env_number("FLEXIE_ARTIFACT_SOURCE_CHARS", 20000, int)
    VOICE_LISTEN_TIMEOUT = _env_number("FLEXIE_VOICE_LISTEN_TIMEOUT", 7.0, float)
    CODE_OUTPUT_DIR = os.getenv("FLEXIE_CODE_OUTPUT_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
    OPENAI_BRIDGE_ENABLED = _env_bool("FLEXIE_OPENAI_BRIDGE_ENABLED", False)
    OPENAI_BRIDGE_PORT = _env_number("FLEXIE_OPENAI_BRIDGE_PORT", 9899, int)
    CHEAP_FIRST_ENABLED = _env_bool("FLEXIE_CHEAP_FIRST_ENABLED", True)
    ARTIFACT_BACKUP_DIR = os.getenv("FLEXIE_ARTIFACT_BACKUP_DIR", os.path.join(os.getcwd(), "context", "artifact_backups"))
    SNAP_PATH  = os.path.join(os.getcwd(), "captures", "flexie_snap.png")
    CAPTURE_DIR = os.path.join(os.getcwd(), "captures")
    TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe" # Default Windows path
    VECTOR_DB_PATH = os.path.join(os.getcwd(), "knowledge_index.json")

    # API Keys & Secrets — all providers (hot-reloadable via set_api_key)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    COHERE_API_KEY = os.getenv("COHERE_API_KEY")
    TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
    # Per-provider models (hot-reloadable via set_model)
    GROQ_MODEL      = os.getenv("GROQ_MODEL", SUPPORTED_PROVIDERS["groq"]["default_model"])
    GEMINI_MODEL    = os.getenv("GEMINI_MODEL", SUPPORTED_PROVIDERS["gemini"]["default_model"])
    # Groq legacy alias cleanup: old installs may have GROQ_MODEL=llama-* which is now decommissioned
    if GROQ_MODEL in ("llama-3.1-8b-instant", "llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"):
        GROQ_MODEL = "openai/gpt-oss-20b"
    OPENAI_MODEL    = os.getenv("OPENAI_MODEL", SUPPORTED_PROVIDERS["openai"]["default_model"])
    DEEPSEEK_MODEL  = os.getenv("DEEPSEEK_MODEL", SUPPORTED_PROVIDERS["deepseek"]["default_model"])
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", SUPPORTED_PROVIDERS["anthropic"]["default_model"])
    MISTRAL_MODEL   = os.getenv("MISTRAL_MODEL", SUPPORTED_PROVIDERS["mistral"]["default_model"])
    COHERE_MODEL    = os.getenv("COHERE_MODEL", SUPPORTED_PROVIDERS["cohere"]["default_model"])
    TOGETHER_MODEL  = os.getenv("TOGETHER_MODEL", SUPPORTED_PROVIDERS["together"]["default_model"])
    ACTIVE_PROVIDER = os.getenv("ACTIVE_PROVIDER", "auto")  # auto | groq | openai | deepseek | gemini | anthropic | mistral | ollama
    OLLAMA_URL     = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    OLLAMA_MODEL   = os.getenv("OLLAMA_MODEL", "tinyllama:latest")
    EMAIL_ADDRESS  = os.getenv("FLEXIE_EMAIL", "")
    EMAIL_PASSWORD = os.getenv("FLEXIE_PASS",  "")

    # --- API Key Management (callable from UI) ---
    @classmethod
    def get_api_key(cls, provider: str) -> str:
        """Get raw key for provider id (groq/gemini/openai/deepseek/...)"""
        meta = SUPPORTED_PROVIDERS.get(provider.lower())
        if not meta:
            return os.getenv(provider, "") or ""
        return os.getenv(meta["env"], "") or ""

    @classmethod
    def set_api_key(cls, provider: str, key: str) -> bool:
        """Save single provider key to .env + os.environ + class attr. Returns success."""
        provider = provider.lower().strip()
        meta = SUPPORTED_PROVIDERS.get(provider)
        if meta:
            env_key = meta["env"]
        else:
            # Allow custom env key direct
            env_key = provider.upper() if provider.isupper() else provider
            if not env_key.endswith("_API_KEY"):
                env_key = env_key.upper() + "_API_KEY" if "_" not in env_key else env_key.upper()
        key = (key or "").strip()
        ok = _write_env_file({env_key: key})
        if ok:
            logging.info(f"Config: {env_key} {'set' if key else 'cleared'} via UI")
        return ok

    @classmethod
    def set_many_keys(cls, mapping: dict) -> bool:
        """Batch save {provider_or_env: key}."""
        updates = {}
        for k, v in mapping.items():
            kl = k.lower().strip()
            meta = SUPPORTED_PROVIDERS.get(kl)
            env_key = meta["env"] if meta else (k.upper() if k.isupper() else k)
            updates[env_key] = (v or "").strip()
        return _write_env_file(updates)

    @classmethod
    def get_all_keys_masked(cls) -> dict:
        """Return {provider: masked_key} for UI display."""
        out = {}
        for pid, meta in SUPPORTED_PROVIDERS.items():
            raw = os.getenv(meta["env"], "")
            out[pid] = {"env": meta["env"], "label": meta["label"], "masked": _mask_key(raw) if raw else "", "has_key": bool(raw), "help": meta["help"]}
        # Ollama extras
        out["ollama"] = {"env": "OLLAMA_URL", "label": "Ollama (Local)", "masked": cls.OLLAMA_URL, "has_key": True, "help": "ollama.com"}
        return out

    @classmethod
    def get_provider_status(cls) -> dict:
        """Quick status for UI badges: {provider: {has_key, masked}}"""
        return cls.get_all_keys_masked()

    @classmethod
    def get_model(cls, provider: str) -> str:
        meta = SUPPORTED_PROVIDERS.get(provider.lower())
        if not meta:
            return os.getenv(f"{provider.upper()}_MODEL", "")
        return os.getenv(meta["model_env"], meta["default_model"])

    @classmethod
    def set_model(cls, provider: str, model: str) -> bool:
        provider = provider.lower().strip()
        meta = SUPPORTED_PROVIDERS.get(provider)
        env_key = meta["model_env"] if meta else f"{provider.upper()}_MODEL"
        model = (model or "").strip()
        if not model:
            return False
        return _write_env_file({env_key: model})

    @classmethod
    def get_available_models(cls, provider: str) -> list:
        meta = SUPPORTED_PROVIDERS.get(provider.lower())
        return list(meta["models"]) if meta and "models" in meta else []

    @classmethod
    def get_active_provider(cls) -> str:
        return os.getenv("ACTIVE_PROVIDER", cls.ACTIVE_PROVIDER)

    @classmethod
    def set_active_provider(cls, provider: str) -> bool:
        provider = (provider or "auto").strip().lower()
        return _write_env_file({"ACTIVE_PROVIDER": provider})

    @classmethod
    def reload(cls):
        """Re-read .env and refresh class attrs (after external edit). Handles model defaults correctly."""
        from dotenv import load_dotenv
        # Read raw file to know what is actually persisted vs lingering env
        file_data = _read_env_file()
        load_dotenv(_env_path(), override=True)
        for _pid, meta in SUPPORTED_PROVIDERS.items():
            # Key
            if meta["env"] in file_data:
                setattr(cls, meta["env"], file_data[meta["env"]] or None)
            else:
                # Not in file — check if it was deleted -> clear env
                if meta["env"] not in file_data and os.getenv(meta["env"]) is not None and meta["env"] not in file_data:
                    # Keep env if it exists but file doesn't have it (system env) — don't clear
                    setattr(cls, meta["env"], os.getenv(meta["env"]))
                else:
                    setattr(cls, meta["env"], None)
            if "model_env" in meta:
                if meta["model_env"] in file_data and file_data[meta["model_env"]]:
                    setattr(cls, meta["model_env"], file_data[meta["model_env"]])
                    os.environ[meta["model_env"]] = file_data[meta["model_env"]]
                else:
                    # No persisted model -> use default and clear lingering env
                    default = meta["default_model"]
                    setattr(cls, meta["model_env"], os.getenv(meta["model_env"], default) if meta["model_env"] in file_data else default)
                    if meta["model_env"] not in file_data and meta["model_env"] in os.environ:
                        # If file doesn't have it, ensure env doesn't shadow default
                        if file_data.get(meta["model_env"], "") == "":
                            # Keep env as is if system set, but class uses default
                            pass
        cls.ACTIVE_PROVIDER = file_data.get("ACTIVE_PROVIDER", os.getenv("ACTIVE_PROVIDER", "auto")) or "auto"
        cls.OLLAMA_URL = file_data.get("OLLAMA_URL", os.getenv("OLLAMA_URL", cls.OLLAMA_URL))
        cls.OLLAMA_MODEL = file_data.get("OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", cls.OLLAMA_MODEL))
        cls.EMAIL_ADDRESS = file_data.get("FLEXIE_EMAIL", os.getenv("FLEXIE_EMAIL", ""))
        cls.EMAIL_PASSWORD = file_data.get("FLEXIE_PASS", os.getenv("FLEXIE_PASS", ""))
        cls.CONVERSATION_HISTORY_TURNS = _env_number("FLEXIE_CONVERSATION_HISTORY_TURNS", cls.CONVERSATION_HISTORY_TURNS, int)
        cls.CONVERSATION_HISTORY_CHARS = _env_number("FLEXIE_CONVERSATION_HISTORY_CHARS", cls.CONVERSATION_HISTORY_CHARS, int)
        cls.ROUTING_CONTEXT_TURNS = _env_number("FLEXIE_ROUTING_CONTEXT_TURNS", cls.ROUTING_CONTEXT_TURNS, int)
        cls.LLM_REQUEST_TIMEOUT = _env_number("FLEXIE_LLM_REQUEST_TIMEOUT", cls.LLM_REQUEST_TIMEOUT, float)
        cls.CODE_MAX_TOKENS = _env_number("FLEXIE_CODE_MAX_TOKENS", cls.CODE_MAX_TOKENS, int)
        cls.ARTIFACT_SOURCE_CHARS = _env_number("FLEXIE_ARTIFACT_SOURCE_CHARS", cls.ARTIFACT_SOURCE_CHARS, int)
        cls.VOICE_LISTEN_TIMEOUT = _env_number("FLEXIE_VOICE_LISTEN_TIMEOUT", cls.VOICE_LISTEN_TIMEOUT, float)
        cls.CODE_OUTPUT_DIR = os.getenv("FLEXIE_CODE_OUTPUT_DIR", cls.CODE_OUTPUT_DIR)
        cls.ARTIFACT_BACKUP_DIR = os.getenv("FLEXIE_ARTIFACT_BACKUP_DIR", cls.ARTIFACT_BACKUP_DIR)
    
    # Available Modes
    MODES = ["professional", "developer", "hacker", "minimal", "focus"]

    SYSTEM_PROMPT_STANDARD = (
        "You are Flexie, a warm, witty AI companion with the personality of Jarvis "
        "from Iron Man — for your user, Dhanush. "
        "You control the screen, browser, and system, so act on requests directly.\n"
        "VOICE RULES (your replies are SPOKEN aloud, so write for the ear):\n"
        "- Conversational and personable: natural contractions ('I'll', 'that's'), "
        "light humor when it fits, never stiff or robotic.\n"
        "- BRIEF: one to two sentences. Never lists, bullets, or markdown — prose only.\n"
        "- No emojis, no symbols, no stage directions.\n"
        "- Acknowledge actions with flavor: 'On it, sir.' 'Done — the browser awaits.'\n"
        "- For questions, answer first, then stop. No filler like 'Great question'.\n"
        + SELF_KNOWLEDGE
    )

    SYSTEM_PROMPT_HACKER = (
        "You are Flexie 2.0, an advanced AI desktop assistant.\n\n"
        "Your goal is NOT just to respond, but to COMPLETE user tasks using available tools.\n\n"
        "CORE RULES:\n"
        "- Prefer ACTION over conversation.\n"
        "- ALWAYS return a structured tool call for tasks.\n"
        "- DO NOT explain or provide a summary; execute silently in the background.\n"
        "- Standard JSON format only for actions.\n\n"
        "Tool format:\n"
        "{\n"
        '  "tool": "<tool_name>",\n'
        '  "args": { ... }\n'
        "}\n\n"
        "Example:\n"
        'User: "Open Chrome"\n'
        "Response: "
        '{"tool": "open_app", "args": {"name": "chrome"}}\n\n'
        "Do not say what you CAN do. Just DO it."
    )

    SYSTEM_PROMPT_DEVELOPER = (
        "You are Flexie, a developer-first AI assistant for Dhanush.\n"
        "RULES:\n"
        "- Think and respond like a senior engineer: precise, terse, technical.\n"
        "- Prefer code, commands, and tools over explanations.\n"
        "- Lead with the solution/code; explain only if asked.\n"
        "- Use developer tools directly (file edits, terminal, browser) without confirmation.\n"
        "- Skip pleasantries and filler. Answer like a pair programmer.\n"
        + SELF_KNOWLEDGE
    )

    SYSTEM_PROMPT_FOCUS = (
        "You are Flexie in FOCUS mode for Dhanush.\n"
        "RULES:\n"
        "- DO NOT disturb. Only respond to direct commands.\n"
        "- NEVER make suggestions, give tips, or start conversations.\n"
        "- Keep every reply to 10 words or fewer. No prose, no pleasantries.\n"
        "- No reminders, no notifications, no proactive updates.\n"
        "- Answer the command, nothing else.\n"
        + SELF_KNOWLEDGE
    )

    SYSTEM_PROMPT_MINIMAL = (
        "You are Flexie in MINIMAL mode for Dhanush.\n"
        "RULES:\n"
        "- Be extremely terse. Every reply 8 words or fewer.\n"
        "- No greetings, no humor, no filler, no explanations unless asked.\n"
        "- Acknowledge actions with a single word: Done., Opened., Set.\n"
        "- Skip pleasantries entirely. Answer only what is asked.\n"
        + SELF_KNOWLEDGE
    )

    # Per-mode max_tokens caps (None = provider default / 2048)
    MODE_MAX_TOKENS = {
        "professional": None,
        "developer": 1024,
        "hacker": 512,
        "minimal": 64,
        "focus": 64,
    }

    # Path Management
    USER_HOME = os.path.expanduser("~")

    APPS: Dict[str, str] = {
        "chrome":       r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "firefox":      r"C:\Program Files\Mozilla Firefox\firefox.exe",
        "vscode":       os.path.join(USER_HOME, r"AppData\Local\Programs\Microsoft VS Code\Code.exe"),
        "vs code":      os.path.join(USER_HOME, r"AppData\Local\Programs\Microsoft VS Code\Code.exe"),
        "spotify":      os.path.join(USER_HOME, r"AppData\Roaming\Spotify\Spotify.exe"),
        "notepad":      "notepad.exe",
        "calculator":   "calc.exe",
        "cmd":          "cmd.exe",
        "task manager": "taskmgr.exe",
        "word":         r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        "excel":        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        "edge":         r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "vlc":          r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        "whatsapp":     "whatsapp:",
        "youtube":      "https://www.youtube.com",
        "github":       "https://www.github.com",
        "gmail":        "https://mail.google.com",
        "maps":         "https://maps.google.com",
        "classroom":    "https://classroom.google.com",
        "chatgpt":      "https://chatgpt.com",
        "antigravity":  "https://antigravity.ai", 
        "wikipedia":    "https://en.wikipedia.org/wiki/",
        "amazon":       "https://www.amazon.in/s?k=",
        "reddit":       "https://www.reddit.com/search/?q=",
        "github_search":"https://github.com/search?q=",
    }

    FOLDER_SHORTCUTS: Dict[str, str] = {
        "desktop":   os.path.join(USER_HOME, "Desktop"),
        "downloads": os.path.join(USER_HOME, "Downloads"),
        "documents": os.path.join(USER_HOME, "Documents"),
        "music":     os.path.join(USER_HOME, "Music"),
        "pictures":  os.path.join(USER_HOME, "Pictures"),
        "videos":    os.path.join(USER_HOME, "Videos"),
        "d drive":   "D:\\",
        "c drive":   "C:\\",
    }

    # Thresholds & Constraints
    MUSIC_EXTS    = {".mp3", ".wav", ".flac", ".m4a"}
    SEARCH_ROOTS  = [USER_HOME, "D:\\"]
    CPU_ALERT     = 85.0
    BATT_LOW      = 20

    # Handler Defaults
    DEFAULT_CITY          = "Coimbatore"
    DEFAULT_NEWS_CATEGORY = "general"
    DEFAULT_NEWS_COUNT    = 5
    DEFAULT_NEWS_SUMMARY  = 3
    DEFAULT_CLIPBOARD_HISTORY = 10
    DEFAULT_NOTIFY_TIMEOUT   = 300  # seconds
    DEFAULT_REMINDER_MINUTES = 5.0
    TIME_FORMAT            = "%I:%M %p"
    
    # Content Security
    RESTRICTED_WORDS = [
        "sexy", "porn", "xvideo", "xhamster", "brazzers", "fuck", "nude", 
        "hot video", "adult", "erotic", "sex", "sunny leone", "mia khalifa",
        "poker", "gambling", "casino"
    ]
    
    DANGER_DOM_WORDS = [
        "delete", "remove", "format", "purchase", "buy", "pay", "unsubscribe", 
        "transfer", "confirm payment", "logout", "sign out", "deactivate",
        "terminate", "erase", "clear all"
    ]

    # Networking
    UDP_PORT_UI        = 9886
    UDP_PORT_ASSISTANT = 9887

import os
import logging
from typing import Dict, List
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'), override=True)

SUPPORTED_PROVIDERS = {
    "groq":      {"env": "GROQ_API_KEY",      "model_env": "GROQ_MODEL",      "label": "Groq",              "placeholder": "gsk_...", "help": "console.groq.com/keys", "prefix": "gsk_", "default_model": "llama-3.1-8b-instant",
                 "models": ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it", "whisper-large-v3"]},
    "gemini":    {"env": "GEMINI_API_KEY",    "model_env": "GEMINI_MODEL",    "label": "Google Gemini",     "placeholder": "AIza...", "help": "aistudio.google.com/app/apikey", "prefix": "AIza", "default_model": "gemini-1.5-flash",
                 "models": ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-exp"]},
    "openai":    {"env": "OPENAI_API_KEY",    "model_env": "OPENAI_MODEL",    "label": "OpenAI (GPT)",      "placeholder": "sk-...", "help": "platform.openai.com/api-keys", "prefix": "sk-", "default_model": "gpt-4o-mini",
                 "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "o1-mini", "o1-preview", "o3-mini"]},
    "deepseek":  {"env": "DEEPSEEK_API_KEY",  "model_env": "DEEPSEEK_MODEL",  "label": "DeepSeek",          "placeholder": "sk-...", "help": "platform.deepseek.com/api_keys", "prefix": "sk-", "default_model": "deepseek-chat",
                 "models": ["deepseek-chat", "deepseek-reasoner"]},
    "anthropic": {"env": "ANTHROPIC_API_KEY", "model_env": "ANTHROPIC_MODEL", "label": "Anthropic Claude",  "placeholder": "sk-ant-...", "help": "console.anthropic.com/settings/keys", "prefix": "sk-ant-", "default_model": "claude-3-5-sonnet-20241022",
                 "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229", "claude-3-sonnet-20240229"]},
    "mistral":   {"env": "MISTRAL_API_KEY",   "model_env": "MISTRAL_MODEL",   "label": "Mistral AI",        "placeholder": "xxx...", "help": "console.mistral.ai/api-keys", "prefix": "", "default_model": "mistral-small-latest",
                 "models": ["mistral-small-latest", "mistral-large-latest", "open-mistral-7b", "open-mixtral-8x7b", "mistral-embed"]},
    "cohere":    {"env": "COHERE_API_KEY",    "model_env": "COHERE_MODEL",    "label": "Cohere",            "placeholder": "xxx...", "help": "dashboard.cohere.com/api-keys", "prefix": "", "default_model": "command-r-plus",
                 "models": ["command-r-plus", "command-r", "embed-english-v3.0"]},
    "together":  {"env": "TOGETHER_API_KEY",  "model_env": "TOGETHER_MODEL",  "label": "Together AI",       "placeholder": "xxx...", "help": "api.together.xyz/settings/api-keys", "prefix": "", "default_model": "meta-llama/Llama-3-8b-chat-hf",
                 "models": ["meta-llama/Llama-3-8b-chat-hf", "meta-llama/Llama-3-70b-chat-hf", "mistralai/Mixtral-8x7B-Instruct-v0.1"]},
}

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
    except Exception:
        pass
    return data

def _write_env_file(updates: dict) -> bool:
    """Merge updates into .env file atomically."""
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
        except Exception:
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
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
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
        for pid, meta in SUPPORTED_PROVIDERS.items():
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
    
    # Available Modes
    MODES = ["professional", "developer", "hacker", "minimal", "focus", "text", "alert"]

    SYSTEM_PROMPT_STANDARD = (
        "You are Flexie, a concise AI assistant for Dhanush. "
        "CAPABILITIES: You CAN see the screen, control the browser, and manage system settings. "
        "RESPONSE RULES: Be ultra-brief (max 15 words) and direct. If performing an action, just confirm with 'On it' or 'Done'."
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

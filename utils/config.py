import os
import logging
from typing import Dict, List
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'), override=True)

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

_validate_env()

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

    # API Keys & Secrets
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
    OLLAMA_URL     = "http://localhost:11434/api/generate"
    OLLAMA_MODEL   = "tinyllama:latest" # Using smaller model for low RAM environments
    EMAIL_ADDRESS  = os.getenv("FLEXIE_EMAIL", "")
    EMAIL_PASSWORD = os.getenv("FLEXIE_PASS",  "")
    
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

import importlib.util
import subprocess
import sys
import logging

# Pip distribution names. Kept as plain strings (external scripts check
# membership, e.g. `"PyAudio" in REQUIRED_PACKAGES`).
REQUIRED_PACKAGES = [
    "pyttsx3",
    "SpeechRecognition",
    "PyAudio",
    "playwright",
    "pyperclip",
    "pygetwindow",
    "psutil",
    "screen-brightness-control",
    "pycaw",
    "comtypes",
    "google-genai",
    "groq",
    "openai",
    "anthropic",
    "requests",
    "python-dotenv",
    "ddgs",
    "pillow",
    "pytesseract",
    "pymupdf",
    "pyautogui",
    "websockets",
    "nest-asyncio",
    "PyQt6",
    "pygame",
    "edge-tts",
    "vosk",
    "langgraph",
    "chromadb",
    "onnxruntime",
    "docker",
    "webrtcvad-wheels",
]

# Pip name -> import name. Only entries that differ from
# `pip_name.replace("-", "_").lower()`-style guessing need listing, but every
# non-trivial mapping is explicit here so checks never reinstall loop.
IMPORT_NAMES = {
    "SpeechRecognition": "speech_recognition",
    "PyAudio": "pyaudio",
    "python-dotenv": "dotenv",
    "pillow": "PIL",
    "google-genai": "google.genai",
    "screen-brightness-control": "screen_brightness_control",
    "nest-asyncio": "nest_asyncio",
    "edge-tts": "edge_tts",
    "pymupdf": "fitz",
    "webrtcvad-wheels": "webrtcvad",
    "pygetwindow": "pygetwindow",
    "PyQt6": "PyQt6",
}


def _import_name(pip_name: str) -> str:
    if pip_name in IMPORT_NAMES:
        return IMPORT_NAMES[pip_name]
    return pip_name.replace("-", "_")


def install_missing():
    """Install missing distributions. Returns the list of packages that
    could NOT be installed (empty on success). Failures are logged as
    warnings — never silently swallowed."""
    missing = []
    for pkg in REQUIRED_PACKAGES:
        if importlib.util.find_spec(_import_name(pkg)) is None:
            missing.append(pkg)

    failed = []
    if missing:
        print(f"[Installer] Missing packages: {', '.join(missing)}")
        for package in missing:
            try:
                print(f"[Installer] Installing {package}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            except Exception as e:
                logging.warning("[Installer] Failed to install %s: %s", package, e)
                print(f"[Installer] FAILED to install {package}: {e}")
                failed.append(package)

        # Special case for playwright - only if playwright was missing
        if "playwright" in missing and "playwright" not in failed:
            print("[Installer] Installing Playwright browsers...")
            try:
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            except Exception as e:
                logging.warning("[Installer] Playwright browser install failed: %s", e)
                print(f"[Installer] FAILED to install Playwright browsers: {e}")
                failed.append("playwright-browsers")

        if failed:
            print(f"[Installer] {len(failed)} package(s) still missing: {', '.join(failed)}")
        else:
            print("[Installer] All missing packages processed.")
    else:
        print("[Installer] All dependencies satisfied.")
    return failed

if __name__ == "__main__":
    install_missing()

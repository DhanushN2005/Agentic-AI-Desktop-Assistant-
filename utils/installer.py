import importlib.util
import subprocess
import sys
import logging

REQUIRED_PACKAGES = [
    "pyttsx3",
    "SpeechRecognition",
    "PyAudio",
    "playwright",
    "pyperclip",
    "pygetwindow",
    "psutil",
    "screen_brightness_control",
    "pycaw",
    "comtypes",
    "google-genai",
    "groq",
    "requests",
    "python-dotenv",
    "ddgs",
    "pillow",
    "pytesseract",
    "pyautogui",
    "websockets",
    "nest_asyncio",
    "PyQt6",
    "pygame",
    "edge-tts"
]

def install_missing():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        # Map package name to actual import name
        import_map = {
            "SpeechRecognition": "speech_recognition",
            "PyAudio": "pyaudio",
            "python-dotenv": "dotenv",
            "pillow": "PIL",
            "google-genai": "google.genai",
            "screen-brightness-control": "screen_brightness_control"
        }

        import_name = import_map.get(pkg, pkg.replace("-", "_"))

        if importlib.util.find_spec(import_name) is None:
            missing.append(pkg)

    if missing:
        print(f"[Installer] Missing packages: {', '.join(missing)}")
        for package in missing:
            try:
                print(f"[Installer] Installing {package}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            except Exception as e:
                logging.debug("[utils/installer.py:53] Swallowed exception: %s: %s", type(e).__name__, e)
                print(f"[Installer] Failed to install {package}: {e}")

        # Special case for playwright - only if playwright was missing
        if "playwright" in missing:
            print("[Installer] Installing Playwright browsers...")
            try:
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            except Exception as _e:
                logging.debug("[utils/installer.py:61] Swallowed exception: %s: %s", type(_e).__name__, _e)
                pass

        print("[Installer] All missing packages processed.")
    else:
        print("[Installer] All dependencies satisfied.")

if __name__ == "__main__":
    install_missing()

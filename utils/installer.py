import importlib.util
import subprocess
import sys

REQUIRED_PACKAGES = [
    "pyttsx3",
    "SpeechRecognition",
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
    "duckduckgo_search",
    "pillow",
    "pytesseract",
    "pyautogui",
    "websockets",
    "nest_asyncio",
    "PyQt6",
    "pygame"
]

def install_missing():
    missing = []
    for pkg in REQUIRED_PACKAGES:
        # Map package name to actual import name
        import_map = {
            "SpeechRecognition": "speech_recognition",
            "python-dotenv": "dotenv",
            "pillow": "PIL",
            "google-genai": "google.genai",
            "screen-brightness-control": "screen_brightness_control",
            "duckduckgo-search": "duckduckgo_search"
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
                print(f"[Installer] Failed to install {package}: {e}")

        # Special case for playwright - only if playwright was missing
        if "playwright" in missing:
            print("[Installer] Installing Playwright browsers...")
            try:
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
            except Exception:
                pass

        print("[Installer] All missing packages processed.")
    else:
        print("[Installer] All dependencies satisfied.")

if __name__ == "__main__":
    install_missing()

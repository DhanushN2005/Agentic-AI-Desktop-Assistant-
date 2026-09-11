import pyautogui
import pytesseract
from PIL import Image
import os
import time
import datetime
import subprocess
from utils.config import Config

class VisionEngine:
    def __init__(self):
        self.history = []
        self.last_screenshot_path = None
        # Ensure capture directory exists
        self.capture_dir = Config.CAPTURE_DIR
        if not os.path.exists(self.capture_dir):
            os.makedirs(self.capture_dir, exist_ok=True)
            
        # Set Tesseract binary path from config
        if hasattr(Config, 'TESSERACT_PATH'):
            pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_PATH
            
        # Verify Tesseract installation
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            print(f"[Vision Warning]: Tesseract-OCR not found at {Config.TESSERACT_PATH}. OCR features will be disabled.")

    def capture_screen(self, path: str = None) -> str:
        """Captures a screenshot with timestamp and adds to history."""
        try:
            if not path:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"flexie_snap_{timestamp}.png"
                path = os.path.join(self.capture_dir, filename)
            
            pyautogui.screenshot(path)
            self.last_screenshot_path = path
            self.history.append(path)
            
            # Keep history manageable (last 50)
            if len(self.history) > 50:
                self.history.pop(0)
                
            return path
        except Exception as e:
            msg = f"Vision Capture Error: {e}"
            print(f"[Vision]: {msg}")
            return f"ERROR: {msg}"

    def show_last_screenshot(self) -> str:
        """Opens the last captured screenshot in the default viewer."""
        try:
            if self.last_screenshot_path and os.path.exists(self.last_screenshot_path):
                os.startfile(self.last_screenshot_path)
                return f"Opening your last screenshot, Dhanush."
            return "I don't have a record of any recent screenshots to show you."
        except Exception as e:
            return f"I couldn't open the screenshot because: {str(e)}"

    def delete_last_screenshot(self) -> str:
        """Deletes the most recent screenshot."""
        try:
            if self.last_screenshot_path and os.path.exists(self.last_screenshot_path):
                os.remove(self.last_screenshot_path)
                old_path = self.last_screenshot_path
                self.last_screenshot_path = self.history[-2] if len(self.history) > 1 else None
                if old_path in self.history: self.history.remove(old_path)
                return "I've deleted the last screenshot for you."
            return "There are no recent screenshots available to delete."
        except Exception as e:
            return f"I had an issue deleting the file: {str(e)}"

    def open_screenshot_folder(self) -> str:
        """Opens the folder containing screenshots."""
        try:
            os.startfile(self.capture_dir)
            return "Opening your screenshots folder now."
        except Exception as e:
            return f"I couldn't open the folder. There might be a system path issue."

    def read_screen_text(self) -> str:
        """Captures screen and performs OCR."""
        try:
            path = self.capture_screen()
            if "ERROR" in path: 
                return "I couldn't capture the screen to read the text."
            
            text = pytesseract.image_to_string(Image.open(path)).strip()
            return text if text else "I scanned the screen but couldn't detect any readable text."
        except Exception as e:
            return f"I ran into an issue while analyzing the screen: {str(e)}"

    def launch_camera(self) -> str:
        """Launches the built-in Windows Camera app."""
        try:
            # start microsoft.windows.camera:
            subprocess.Popen('start microsoft.windows.camera:', shell=True)
            time.sleep(1.0)
            # Press enter to capture photo
            pyautogui.press('enter')
            return "Opening camera and capturing photo."
        except Exception as e:
            return f"Failed to launch camera: {e}"

    def analyze_screen(self, brain_instance, prompt: str = "Describe what is on my screen right now.") -> str:
        """Captures screen and gets an AI description."""
        try:
            path = self.capture_screen()
            if "ERROR" in path: 
                return "I'm unable to see your screen right now due to a capture error."
            return brain_instance.ask(prompt, img_path=path)
        except Exception as e:
            return f"I encountered a vision analysis error: {str(e)}"

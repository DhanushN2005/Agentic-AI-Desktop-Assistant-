import datetime
import logging
import os
import time

from utils.config import Config
from utils.lazy import LazyModule

pyautogui = LazyModule("pyautogui")
pytesseract = LazyModule("pytesseract")
Image = LazyModule("PIL", "Image")


class VisionEngine:
    def __init__(self):
        self.history = []
        self.last_screenshot_path = None
        # Ensure capture directory exists
        self.capture_dir = Config.CAPTURE_DIR
        if not os.path.exists(self.capture_dir):
            os.makedirs(self.capture_dir, exist_ok=True)

        self._ocr_checked = False

    def _ensure_ocr(self) -> None:
        """Locate/verify Tesseract on first OCR use (importing it and spawning it at startup was slow)."""
        if self._ocr_checked:
            return
        self._ocr_checked = True
        if hasattr(Config, 'TESSERACT_PATH'):
            pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_PATH
        try:
            pytesseract.get_tesseract_version()
        except Exception as _e:
            logging.debug("Tesseract check failed: %s: %s", type(_e).__name__, _e)
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
            logging.debug("[engines/vision.py:49] Swallowed exception: %s: %s", type(e).__name__, e)
            msg = f"Vision Capture Error: {e}"
            print(f"[Vision]: {msg}")
            return f"ERROR: {msg}"

    def show_last_screenshot(self) -> str:
        """Opens the last captured screenshot in the default viewer."""
        try:
            if self.last_screenshot_path and os.path.exists(self.last_screenshot_path):
                os.startfile(self.last_screenshot_path)
                return f"Opening your last screenshot, {Config.USER_NAME}."
            return "I don't have a record of any recent screenshots to show you."
        except Exception as e:
            logging.debug("[engines/vision.py:61] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I couldn't open the screenshot because: {str(e)}"

    def delete_last_screenshot(self) -> str:
        """Deletes the most recent screenshot."""
        try:
            if self.last_screenshot_path and os.path.exists(self.last_screenshot_path):
                os.remove(self.last_screenshot_path)
                old_path = self.last_screenshot_path
                self.last_screenshot_path = self.history[-2] if len(self.history) > 1 else None
                if old_path in self.history:
                    self.history.remove(old_path)
                return "I've deleted the last screenshot for you."
            return "There are no recent screenshots available to delete."
        except Exception as e:
            logging.debug("[engines/vision.py:74] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I had an issue deleting the file: {str(e)}"

    def open_screenshot_folder(self) -> str:
        """Opens the folder containing screenshots."""
        try:
            os.startfile(self.capture_dir)
            return "Opening your screenshots folder now."
        except Exception as _e:
            logging.debug("[engines/vision.py:82] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return "I couldn't open the folder. There might be a system path issue."

    def read_screen_text(self) -> str:
        """Captures screen and performs OCR."""
        try:
            path = self.capture_screen()
            if "ERROR" in path:
                return "I couldn't capture the screen to read the text."

            self._ensure_ocr()
            text = pytesseract.image_to_string(Image.open(path)).strip()
            return text if text else "I scanned the screen but couldn't detect any readable text."
        except Exception as e:
            logging.debug("[engines/vision.py:94] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"I ran into an issue while analyzing the screen: {str(e)}"

    @staticmethod
    def _active_window_title() -> str:
        try:
            import pygetwindow as gw
            win = gw.getActiveWindow()
            return (win.title or "") if win else ""
        except Exception as _e:
            logging.debug("active window probe failed: %s", _e)
            return ""

    def launch_camera(self, wait_seconds: float = 6.0) -> str:
        """Launch the Windows Camera app (no shell). Enter is sent only once the
        Camera window is really in the foreground; otherwise the photo is left to the user."""
        try:
            os.startfile("microsoft.windows.camera:")
        except Exception as e:
            logging.debug("camera launch failed: %s: %s", type(e).__name__, e)
            return f"Failed to launch camera: {e}"
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if "camera" in self._active_window_title().lower():
                time.sleep(0.5)  # let the preview initialise
                if "camera" in self._active_window_title().lower():
                    try:
                        pyautogui.press('enter')
                    except Exception as e:
                        return f"Camera opened but I couldn't press capture: {e}"
                    return "Opening camera and capturing photo."
            time.sleep(0.25)
        return "I opened the Camera app, but it didn't come to the front, so I didn't press anything. Tap capture yourself."

    def analyze_screen(self, brain_instance, prompt: str = "Describe what is on my screen right now.") -> str:
        """Captures the screen and gets an AI description.

        If no vision model can answer, falls back to reading the text on screen (OCR) and says so,
        instead of guessing or searching the web.
        """
        try:
            path = self.capture_screen()
            if "ERROR" in path:
                return "I'm unable to see your screen right now due to a capture error."
            reply = brain_instance.ask(prompt, img_path=path)
            from core.brain import VISION_UNAVAILABLE_MSG
            if not reply or str(reply).startswith(VISION_UNAVAILABLE_MSG[:40]):
                text = self._ocr_path(path)
                if text:
                    return ("My vision model isn't responding, so I can't describe the picture, "
                            f"but this is the text I can read on your screen: {text[:600]}")
                return VISION_UNAVAILABLE_MSG
            return reply
        except Exception as e:
            logging.debug("vision analysis error: %s: %s", type(e).__name__, e)
            return f"I encountered a vision analysis error: {str(e)}"

    def _ocr_path(self, path: str) -> str:
        """OCR text of an image file, or '' if OCR is unavailable."""
        try:
            self._ensure_ocr()
            return " ".join(pytesseract.image_to_string(Image.open(path)).split())
        except Exception as e:
            logging.debug("OCR unavailable: %s: %s", type(e).__name__, e)
            return ""

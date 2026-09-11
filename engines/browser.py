import os
import time
import logging
import csv
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from utils.config import Config

class BrowserEngine:
    """Core DOM Automation Layer for Flexie 2.0."""
    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.logger = logging.getLogger("Flexie.Browser")
        self.last_url = None
        self.user_data_dir = os.path.join(os.getcwd(), "browser_session")

    def is_healthy(self) -> bool:
        """Heartbeat check to verify the browser is responsive and page is functional."""
        try:
            if not self.playwright or not self.context or not self.page:
                return False
            if self.page.is_closed():
                return False
            # Run a quick lightweight evaluate to test responsiveness
            self.page.evaluate("1 + 1")
            return True
        except Exception as e:
            self.logger.warning(f"Browser heartbeat check failed: {e}")
            return False

    def _limit_tabs(self):
        """Closes excess inactive tabs to prevent memory leaks."""
        try:
            if self.context:
                pages = self.context.pages
                if len(pages) > 5:
                    self.logger.info(f"Closing {len(pages) - 5} excess tabs to prevent memory leaks.")
                    for p in pages[:-1]: # Keep the last active page
                        if p != self.page:
                            try: p.close()
                            except: pass
        except Exception as e:
            self.logger.warning(f"Failed to limit tabs: {e}")

    def _ensure_session(self):
        """Maintains a persistent browser session with user data for logins."""
        import threading
        curr_thread = threading.get_ident()
        
        # If thread changed, we must re-init Playwright references as it's not thread-safe.
        # We nullify the references without calling thread-unsafe self.cleanup() on the old session.
        if hasattr(self, "_thread_id") and self._thread_id != curr_thread:
            self.logger.warning("Thread change detected. Resetting browser session references safely...")
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
        
        self._thread_id = curr_thread

        # Browser heartbeat check for existing session
        if self.playwright and self.context and self.page:
            if not self.is_healthy():
                self.logger.warning("Browser session is unhealthy or crashed. Triggering safe auto-recovery...")
                self.page = None
                self.context = None
                self.browser = None

        if not self.browser or not self.context:
            try:
                # Check for existing lock file in session dir and force clear it if recovering
                lock_file = os.path.join(self.user_data_dir, "SingletonLock")
                if os.path.exists(lock_file):
                    self.logger.warning("Stale browser session lock detected. Force clearing lock...")
                    try:
                        os.remove(lock_file)
                    except Exception as le:
                        self.logger.error(f"Could not remove SingletonLock: {le}")
                
                if not self.playwright:
                    try:
                        import asyncio
                        loop = asyncio.get_running_loop()
                        if loop:
                            import nest_asyncio
                            nest_asyncio.apply()
                    except RuntimeError:
                        pass
                    self.playwright = sync_playwright().start()
                
                # Stealth Launch: No "Automation" bar, No "Unsupported Flag" warnings
                self.context = self.playwright.chromium.launch_persistent_context(
                    user_data_dir=self.user_data_dir,
                    channel="chrome", 
                    headless=False,
                    no_viewport=True,
                    args=[
                        "--start-maximized", 
                        "--disable-infobars",
                        "--test-type",
                        "--disable-blink-features=AutomationControlled",
                        "--excludeSwitches=enable-automation",
                        "--disable-extensions",
                        "--disable-session-crashed-bubble",
                        "--disable-infobars",
                        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ],
                    ignore_default_args=["--enable-automation"]
                )
                self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                
                # Flexie 3.0: Nuke-Mode Ad Skipper client-side injection.
                # Runs globally inside Chrome using setInterval to avoid thread-safety violations in Python.
                ad_skipper_js = """
                (function() {
                    if (window.flexieAdSkipperRegistered) return;
                    window.flexieAdSkipperRegistered = true;
                    const adSelectors = ['.ad-showing', '.ad-interrupting', '.ytp-ad-player-overlay'];
                    const skipSelectors = [
                        '.ytp-ad-skip-button', '.ytp-ad-skip-button-modern', 
                        '.ytp-skip-ad-button', '.ytp-ad-skip-button-text',
                        '.ytp-ad-skip-button-slot', '.ytp-ad-skip-button-container'
                    ];
                    setInterval(() => {
                        for (let s of skipSelectors) {
                            let btn = document.querySelector(s);
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                            }
                        }
                        const isAdShowing = adSelectors.some(s => document.querySelector(s) !== null);
                        const video = document.querySelector('video');
                        if (isAdShowing && video) {
                            if (video.playbackRate < 16.0) {
                                video.playbackRate = 16.0;
                                video.muted = true;
                            }
                            if (video.duration - video.currentTime < 1.5) {
                                video.currentTime = video.duration - 0.1;
                            }
                        }
                        document.querySelectorAll('.ytp-ad-overlay-close-button').forEach(el => {
                            if (el.offsetParent !== null) el.click();
                        });
                    }, 1000);
                })();
                """
                self.context.add_init_script(ad_skipper_js)
                self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
                self.browser = self.context.browser if hasattr(self.context, 'browser') else None
                
                # Set a default timeout for all actions
                self.page.set_default_timeout(10000)
            except Exception as e:
                self.logger.error(f"Browser Init Error: {e}")
                # Secondary recovery logic: clear locks and retry once more
                try:
                    lock_file = os.path.join(self.user_data_dir, "SingletonLock")
                    if os.path.exists(lock_file):
                        os.remove(lock_file)
                except: pass
                return False
        return True

    def navigate(self, url: str) -> str:
        if not self._ensure_session(): return "Failed to open browser."
        self._limit_tabs() # Limit tabs before navigating
        if not url.startswith("http"): url = f"https://{url}"
        
        # Priority 1 & 6: Navigate with verification and self-healing session recovery
        max_attempts = 2
        last_err = ""
        for attempt in range(max_attempts):
            try:
                self._check_interruption()
                
                # If session is detected unhealthy or crashed, trigger recovery before navigating
                if attempt > 0 or not self.is_healthy():
                    self.logger.warning("Session unhealthy during navigation. Re-initializing browser session...")
                    self.page = None
                    self.context = None
                    self.browser = None
                    if not self._ensure_session():
                        return "Failed to auto-recover browser session during navigation."
                
                # LATENCY TIP: 'domcontentloaded' is much faster than 'networkidle'
                self.page.goto(url, wait_until="domcontentloaded", timeout=12000)
                self.last_url = url
                self._check_captcha()
                
                # Verification Check: verify page loaded and URL matches
                if self.is_healthy():
                    current_page_url = self.page.url.lower()
                    # Strip slashes and protocols to compare cleanly
                    clean_target = url.lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
                    clean_actual = current_page_url.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
                    
                    if clean_target in clean_actual or clean_actual in clean_target:
                        break # Successful verification
                    else:
                        self.logger.warning(f"Verification mismatch: Expected {clean_target}, got actual URL: {clean_actual}")
                
            except Exception as e:
                last_err = str(e)
                self.logger.error(f"Navigation attempt {attempt+1} failed: {e}")
                time.sleep(0.5)
        
        # Double check final health state
        if not self.is_healthy():
            from utils.helpers import is_online
            if not is_online():
                return "I couldn't load the page because you are currently offline. Please check your internet connection."
            return f"Navigation failed after self-healing attempts. Details: {last_err}"
            
        # Explicitly trigger ad skipper on YouTube navigation
        if "youtube.com" in url:
            try:
                self.page.evaluate("""() => {
                    if (window.flexieAdSkipperRegistered) return;
                    window.flexieAdSkipperRegistered = true;
                    const adSelectors = ['.ad-showing', '.ad-interrupting', '.ytp-ad-player-overlay'];
                    const skipSelectors = [
                        '.ytp-ad-skip-button', '.ytp-ad-skip-button-modern', 
                        '.ytp-skip-ad-button', '.ytp-ad-skip-button-text',
                        '.ytp-ad-skip-button-slot', '.ytp-ad-skip-button-container'
                    ];
                    setInterval(() => {
                        for (let s of skipSelectors) {
                            let btn = document.querySelector(s);
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                            }
                        }
                        const isAdShowing = adSelectors.some(s => document.querySelector(s) !== null);
                        const video = document.querySelector('video');
                        if (isAdShowing && video) {
                            if (video.playbackRate < 16.0) {
                                video.playbackRate = 16.0;
                                video.muted = true;
                            }
                            if (video.duration - video.currentTime < 1.5) {
                                video.currentTime = video.duration - 0.1;
                            }
                        }
                        document.querySelectorAll('.ytp-ad-overlay-close-button').forEach(el => {
                            if (el.offsetParent !== null) el.click();
                        });
                    }, 1000);
                }""")
            except: pass
            
        return f"Navigated to {url}"

    def highlight_element(self, selector: str) -> bool:
        """Draws a red border around the element to show the user what will be clicked."""
        if not self.page: return False
        try:
            if not (selector.startswith(".") or selector.startswith("#") or selector.startswith("[")):
                # If text-based, find the actual element first
                self.page.evaluate(f"""() => {{
                    const el = Array.from(document.querySelectorAll('*')).find(e => e.innerText === "{selector}" || e.textContent === "{selector}");
                    if (el) {{
                        el.style.outline = '4px solid red';
                        el.style.backgroundColor = 'rgba(255,0,0,0.2)';
                        el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                    }}
                }}""")
            else:
                self.page.add_style_tag(content=f"{selector} {{ outline: 4px solid red !important; background-color: rgba(255,0,0,0.2) !important; }}")
                self.page.locator(selector).first.scroll_into_view_if_needed()
            return True
        except: return False

    def is_risky(self, selector: str) -> bool:
        """Checks if the target text contains dangerous keywords."""
        s_lower = selector.lower()
        return any(word in s_lower for word in Config.DANGER_DOM_WORDS)

    def click_element(self, selector: str) -> str:
        if not self.page: return "No active page."
        try:
            self._check_interruption()
            # Highlight first
            self.highlight_element(selector)
            
            # Save starting state for verification
            start_url = self.page.url
            start_pages_count = len(self.context.pages) if self.context else 1
            try:
                start_text_len = len(self.page.inner_text("body"))
            except:
                start_text_len = 0
            
            # Robust selector attempt
            if selector.startswith((".", "#", "[")):
                self.page.click(selector, timeout=5000)
            else:
                # Try text match first, then ARIA role for better accessibility support
                try:
                    self.page.get_by_text(selector, exact=False).first.click(timeout=3000)
                except:
                    self.page.click(f"text='{selector}'", timeout=3000)
            
            # Cleanup outline
            self.page.evaluate("() => { document.querySelectorAll('*').forEach(e => { e.style.outline = ''; e.style.backgroundColor = ''; }); }")
            self._check_captcha()
            
            # Post-click verification (wait a brief moment to allow page load/navigation)
            time.sleep(0.5)
            end_url = self.page.url
            end_pages_count = len(self.context.pages) if self.context else 1
            try:
                end_text_len = len(self.page.inner_text("body"))
            except:
                end_text_len = 0
                
            # If nothing seems to have changed, we can suspect standard click did not register
            if start_url == end_url and start_pages_count == end_pages_count and start_text_len == end_text_len:
                self.logger.warning(f"Standard click on '{selector}' executed but detected no visual or URL change. Triggering visual coordinate click fallback...")
                raise Exception("No state change detected after standard click.")
                
            return f"Successfully clicked on {selector}."
        except Exception as e:
            if "Interrupted" in str(e): raise e
            self.logger.warning(f"Standard click failed or unverified for {selector}: {e}. Triggering visual click fallback...")
            
            # Try visual click fallback
            try:
                if self._visual_click_fallback(selector):
                    return f"Successfully clicked on {selector} using visual coordinate mapping."
            except Exception as ve:
                self.logger.error(f"Visual click fallback error for {selector}: {ve}")
                
            return f"I couldn't click on {selector}. It might be hidden or the name is slightly different."

    def _visual_click_fallback(self, selector: str) -> bool:
        """Captures a screenshot of the browser page, sends it to Gemini to map coordinates,
        and executes a click using Playwright's mouse and physical coordinates.
        """
        import re
        import json
        import pyautogui
        try:
            import pygetwindow as gw
        except ImportError:
            gw = None

        self.logger.info(f"Visual click fallback: Attempting visual coordinate click for '{selector}'...")
        temp_path = os.path.join(Config.CAPTURE_DIR, f"click_fallback_{int(time.time())}.png")
        
        try:
            # 1. Take viewport screenshot
            os.makedirs(Config.CAPTURE_DIR, exist_ok=True)
            self.page.screenshot(path=temp_path)
            
            # 2. Build prompt for coordinates extraction
            prompt = (
                f"You are a precise screen coordinate extraction tool.\n"
                f"Identify the EXACT visual center of the button, link, input field, or element matching the description/text: '{selector}'.\n"
                f"Calculate the coordinates relative to the top-left corner of the provided image (0, 0).\n"
                f"Return ONLY a clean JSON object containing 'x' and 'y' properties, for example: {{\"x\": 340, \"y\": 215}}.\n"
                f"Do not write any other explanation or use code blocks. Return ONLY the JSON."
            )
            
            # 3. Request coordinates from Brain
            raw_response = self.orchestrator.brain.ask(prompt, img_path=temp_path)
            self.logger.info(f"Visual click fallback raw coordinate response: {raw_response}")
            
            # Clean up response text in case LLM wraps it in markdown blocks
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
            
            coords = json.loads(cleaned)
            x = int(coords["x"])
            y = int(coords["y"])
            
            # 4. Attempt Playwright mouse click (viewport relative)
            self.page.mouse.click(x, y)
            self.logger.info(f"Visual click fallback: successfully performed page.mouse.click at ({x}, {y})")
            
            # 5. Bring browser to front and perform physical PyAutoGUI click
            if gw:
                try:
                    for w in gw.getAllWindows():
                        if "chrome" in w.title.lower() or (self.page and self.page.title() in w.title):
                            if w.isMinimized:
                                w.restore()
                            w.activate()
                            time.sleep(0.2)
                            break
                except Exception as we:
                    self.logger.warning(f"Could not activate Chrome window for physical click: {we}")
            
            try:
                offsets = self.page.evaluate("""() => {
                    return {
                        screenX: window.screenX,
                        screenY: window.screenY,
                        outerWidth: window.outerWidth,
                        outerHeight: window.outerHeight,
                        innerWidth: window.innerWidth,
                        innerHeight: window.innerHeight
                    }
                }""")
                border_x = max(0, (offsets['outerWidth'] - offsets['innerWidth']) / 2)
                top_bar_h = max(0, offsets['outerHeight'] - offsets['innerHeight'] - 8)
                
                screen_x = int(offsets['screenX'] + border_x + x)
                screen_y = int(offsets['screenY'] + top_bar_h + y)
                
                pyautogui.click(screen_x, screen_y)
                self.logger.info(f"Visual click fallback: successfully performed physical pyautogui.click at ({screen_x}, {screen_y})")
            except Exception as pe:
                self.logger.warning(f"Physical click failed: {pe}. Falling back to mouse-only click.")
                
            return True
        except Exception as e:
            self.logger.error(f"Visual click fallback failed: {e}")
            return False
        finally:
            # Clean up the screenshot
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass

    def fill_field(self, selector: str, value: str) -> str:
        if not self.page: return "No active page."
        try:
            self._check_interruption()
            # Highlight first
            self.highlight_element(selector)
            
            # Robust selector attempt
            locator = None
            if selector.startswith((".", "#", "[")):
                locator = self.page.locator(selector).first
            else:
                # Try locating by placeholder, label, or text
                try:
                    locator = self.page.get_by_placeholder(selector, exact=False).first
                    locator.wait_for(timeout=1000)
                except:
                    try:
                        locator = self.page.get_by_label(selector, exact=False).first
                        locator.wait_for(timeout=1000)
                    except:
                        locator = self.page.locator(f"text='{selector}'").first
            
            if locator:
                locator.fill(value, timeout=5000)
                # Verification Check
                time.sleep(0.2)
                try:
                    actual_val = locator.input_value(timeout=1000)
                    if actual_val != value:
                        raise Exception(f"Input value mismatch. Expected '{value}', got '{actual_val}'")
                except Exception as val_err:
                    self.logger.warning(f"Input verification failed: {val_err}. Retrying standard fill...")
                    locator.fill(value, timeout=3000)
                    time.sleep(0.2)
                    if locator.input_value(timeout=1000) != value:
                        raise Exception("Input verification failed twice.")
            else:
                raise Exception("Could not resolve locator for standard fill.")
            
            self._check_captcha()
            return f"Successfully filled {selector}."
        except Exception as e:
            if "Interrupted" in str(e): raise e
            self.logger.warning(f"Standard fill failed or unverified for {selector}: {e}. Triggering visual fill fallback...")
            
            try:
                if self._visual_fill_fallback(selector, value):
                    return f"Successfully filled {selector} with '{value}' using visual coordinate mapping."
            except Exception as ve:
                self.logger.error(f"Visual fill fallback error for {selector}: {ve}")
                
            return f"I couldn't fill the field {selector}. Try using a more specific name."

    def _visual_fill_fallback(self, selector: str, value: str) -> bool:
        """Captures a screenshot of the browser page, sends it to Gemini to map the input coordinate,
        focuses the input, and simulates key typing.
        """
        import re
        import json
        import pyautogui
        try:
            import pygetwindow as gw
        except ImportError:
            gw = None

        self.logger.info(f"Visual fill fallback: Attempting visual coordinate fill for '{selector}'...")
        temp_path = os.path.join(Config.CAPTURE_DIR, f"fill_fallback_{int(time.time())}.png")
        
        try:
            # 1. Take viewport screenshot
            os.makedirs(Config.CAPTURE_DIR, exist_ok=True)
            self.page.screenshot(path=temp_path)
            
            # 2. Build prompt for coordinates extraction
            prompt = (
                f"You are a precise screen coordinate extraction tool.\n"
                f"Identify the EXACT visual center of the text input field, textarea, or input box matching the description/text: '{selector}'.\n"
                f"Calculate the coordinates relative to the top-left corner of the provided image (0, 0).\n"
                f"Return ONLY a clean JSON object containing 'x' and 'y' properties, for example: {{\"x\": 340, \"y\": 215}}.\n"
                f"Do not write any other explanation or use code blocks. Return ONLY the JSON."
            )
            
            # 3. Request coordinates from Brain
            raw_response = self.orchestrator.brain.ask(prompt, img_path=temp_path)
            self.logger.info(f"Visual fill fallback raw coordinate response: {raw_response}")
            
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
            
            coords = json.loads(cleaned)
            x = int(coords["x"])
            y = int(coords["y"])
            
            # 4. Focus field via viewport relative click and clear it
            self.page.mouse.click(x, y)
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
            self.page.keyboard.type(value, delay=50)
            self.logger.info(f"Visual fill fallback: successfully performed page.mouse.click & keyboard type at ({x}, {y})")
            
            # 5. Coordinate physical click and keystrokes fallback
            if gw:
                try:
                    for w in gw.getAllWindows():
                        if "chrome" in w.title.lower() or (self.page and self.page.title() in w.title):
                            if w.isMinimized:
                                w.restore()
                            w.activate()
                            time.sleep(0.2)
                            break
                except Exception as we:
                    self.logger.warning(f"Could not activate Chrome window for physical fill: {we}")
            
            try:
                offsets = self.page.evaluate("""() => {
                    return {
                        screenX: window.screenX,
                        screenY: window.screenY,
                        outerWidth: window.outerWidth,
                        outerHeight: window.outerHeight,
                        innerWidth: window.innerWidth,
                        innerHeight: window.innerHeight
                    }
                }""")
                border_x = max(0, (offsets['outerWidth'] - offsets['innerWidth']) / 2)
                top_bar_h = max(0, offsets['outerHeight'] - offsets['innerHeight'] - 8)
                
                screen_x = int(offsets['screenX'] + border_x + x)
                screen_y = int(offsets['screenY'] + top_bar_h + y)
                
                pyautogui.click(screen_x, screen_y)
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('backspace')
                pyautogui.write(value, interval=0.01)
                self.logger.info(f"Visual fill fallback: successfully performed physical pyautogui input at ({screen_x}, {screen_y})")
            except Exception as pe:
                self.logger.warning(f"Physical input failed: {pe}. Falling back to virtual-only input.")
                
            return True
        except Exception as e:
            self.logger.error(f"Visual fill fallback failed: {e}")
            return False
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass

    def hover_element(self, selector: str) -> str:
        """Hovers the mouse pointer over a target DOM element."""
        if not self.page: return "No active page."
        try:
            self._check_interruption()
            self.highlight_element(selector)
            
            if selector.startswith((".", "#", "[")):
                self.page.hover(selector, timeout=5000)
            else:
                try:
                    self.page.get_by_text(selector, exact=False).first.hover(timeout=3000)
                except:
                    self.page.hover(f"text='{selector}'", timeout=3000)
                    
            return f"Successfully hovered over {selector}."
        except Exception as e:
            self.logger.warning(f"Standard hover failed for {selector}: {e}. Triggering visual hover fallback...")
            try:
                if self._visual_hover_fallback(selector):
                    return f"Successfully hovered over {selector} using visual coordinate mapping."
            except Exception as ve:
                self.logger.error(f"Visual hover fallback error for {selector}: {ve}")
                
            return f"I couldn't hover over {selector}."

    def _visual_hover_fallback(self, selector: str) -> bool:
        """Captures a screenshot of the browser page, maps the coordinate, and moves the mouse."""
        import re
        import json
        import pyautogui
        try:
            import pygetwindow as gw
        except ImportError:
            gw = None

        self.logger.info(f"Visual hover fallback: Attempting visual coordinate hover for '{selector}'...")
        temp_path = os.path.join(Config.CAPTURE_DIR, f"hover_fallback_{int(time.time())}.png")
        
        try:
            os.makedirs(Config.CAPTURE_DIR, exist_ok=True)
            self.page.screenshot(path=temp_path)
            
            prompt = (
                f"You are a precise screen coordinate extraction tool.\n"
                f"Identify the EXACT visual center of the element matching the description/text: '{selector}' to hover over.\n"
                f"Calculate the coordinates relative to the top-left corner of the provided image (0, 0).\n"
                f"Return ONLY a clean JSON object containing 'x' and 'y' properties, for example: {{\"x\": 340, \"y\": 215}}.\n"
                f"Do not write any other explanation or use code blocks. Return ONLY the JSON."
            )
            
            raw_response = self.orchestrator.brain.ask(prompt, img_path=temp_path)
            
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()
            
            coords = json.loads(cleaned)
            x = int(coords["x"])
            y = int(coords["y"])
            
            # Virtual hover
            self.page.mouse.move(x, y)
            
            # Physical hover
            if gw:
                try:
                    for w in gw.getAllWindows():
                        if "chrome" in w.title.lower() or (self.page and self.page.title() in w.title):
                            if w.isMinimized:
                                w.restore()
                            w.activate()
                            time.sleep(0.2)
                            break
                except Exception as we:
                    self.logger.warning(f"Could not activate Chrome window for physical hover: {we}")
            
            try:
                offsets = self.page.evaluate("""() => {
                    return {
                        screenX: window.screenX,
                        screenY: window.screenY,
                        outerWidth: window.outerWidth,
                        outerHeight: window.outerHeight,
                        innerWidth: window.innerWidth,
                        innerHeight: window.innerHeight
                    }
                }""")
                border_x = max(0, (offsets['outerWidth'] - offsets['innerWidth']) / 2)
                top_bar_h = max(0, offsets['outerHeight'] - offsets['innerHeight'] - 8)
                
                screen_x = int(offsets['screenX'] + border_x + x)
                screen_y = int(offsets['screenY'] + top_bar_h + y)
                
                pyautogui.moveTo(screen_x, screen_y, duration=0.2)
            except Exception as pe:
                self.logger.warning(f"Physical hover failed: {pe}")
                
            return True
        except Exception as e:
            self.logger.error(f"Visual hover fallback failed: {e}")
            return False
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except:
                pass

    def select_dropdown(self, selector: str, option: str) -> str:
        """Selects an option from a dropdown element."""
        if not self.page: return "No active page."
        try:
            self._check_interruption()
            self.highlight_element(selector)
            
            if selector.startswith((".", "#", "[")):
                self.page.select_option(selector, label=option, timeout=5000)
            else:
                try:
                    self.page.locator(f"select:has-text('{selector}')").first.select_option(label=option, timeout=3000)
                except:
                    # Let's try matching custom select elements by clicking and then clicking the option
                    self.click_element(selector)
                    time.sleep(0.3)
                    self.click_element(option)
                    
            return f"Successfully selected option '{option}' from {selector}."
        except Exception as e:
            self.logger.warning(f"Dropdown selection failed for {selector} with option {option}: {e}")
            # Fallback to visual clicking the dropdown, then the option
            try:
                self.logger.info("Triggering visual click sequence for dropdown select fallback...")
                self.click_element(selector)
                time.sleep(0.5)
                self.click_element(option)
                return f"Successfully selected option '{option}' from dropdown {selector} via coordinate-click cascade."
            except Exception as ve:
                self.logger.error(f"Visual dropdown cascade failed: {ve}")
            return f"I couldn't select option {option} in dropdown {selector}."

    def extract_interactive_elements(self) -> str:
        """Retrieves and formats all active buttons, input fields, and links on the page."""
        if not self.page: return "No active page."
        try:
            self._check_interruption()
            js_script = """
            () => {
                const elements = Array.from(document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"]'));
                return elements.map(el => {
                    const rect = el.getBoundingClientRect();
                    const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).display !== 'none';
                    if (!isVisible) return null;
                    
                    let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.id || '';
                    text = text.trim().substring(0, 50);
                    
                    let tag = el.tagName.toLowerCase();
                    let type = el.getAttribute('type') || '';
                    
                    let selector = '';
                    if (el.id) selector = '#' + el.id;
                    else if (el.className) {
                        const classes = Array.from(el.classList).filter(c => !c.includes('active') && !c.includes('hover')).join('.');
                        if (classes) selector = '.' + classes.split(' ')[0];
                    }
                    if (!selector) selector = el.tagName.toLowerCase();
                    
                    return { tag, type, text, selector };
                }).filter(e => e !== null);
            }
            """
            raw_elements = self.page.evaluate(js_script)
            seen = set()
            clean_list = []
            for item in raw_elements:
                if not item['text']: continue
                key = (item['tag'], item['text'])
                if key not in seen:
                    seen.add(key)
                    clean_list.append(f"- [{item['tag'].upper()}] '{item['text']}' (Selector: {item['selector']})")
                    
            if clean_list:
                result = "\n".join(clean_list[:15])
                return f"I found these interactive elements on the page:\n{result}"
            return "No interactive elements detected on the current view."
        except Exception as e:
            return f"Error gathering interactive elements: {e}"

    def capture_page(self) -> str:
        """Takes a screenshot of the current page."""
        if not self.page: return "No active page."
        try:
            path = os.path.join(Config.CAPTURE_DIR, f"web_snap_{int(time.time())}.png")
            self.page.screenshot(path=path)
            return f"Screenshot saved to {path}"
        except Exception as e:
            return f"Screenshot error: {e}"

    def list_tabs(self) -> str:
        if not self.context: return "No active session."
        pages = self.context.pages
        titles = [f"{i+1}: {p.title()[:30]}" for i, p in enumerate(pages)]
        return f"Open tabs: {', '.join(titles)}"

    def switch_tab(self, index: int) -> str:
        if not self.context: return "No active session."
        pages = self.context.pages
        if 0 < index <= len(pages):
            self.page = pages[index-1]
            self.page.bring_to_front()
            return f"Switched to tab {index}: {self.page.title()}"
        return f"Invalid tab index {index}."

    def new_tab(self, url: str = "https://www.google.com") -> str:
        if not self._ensure_session(): return "Failed to start session."
        self._limit_tabs() # Limit tabs before creating a new one
        self.page = self.context.new_page()
        return self.navigate(url)

    def close_current_tab(self) -> str:
        if not self.page: return "No active page."
        try:
            self.page.close()
            if self.context.pages:
                self.page = self.context.pages[-1]
                return "Closed tab. Switched to previous tab."
            return "Closed tab. No more tabs open."
        except Exception as e:
            return f"Error closing tab: {e}"

    def scroll(self, direction: str = "down") -> str:
        if not self.page: return "No active page."
        try:
            distance = 500 if direction == "down" else -500
            self.page.mouse.wheel(0, distance)
            return f"Scrolled {direction}."
        except:
            return "Scroll failed."

    def extract_page_data(self, mode: str = "text") -> str:
        """Extracts visible text, links, or tables."""
        if not self.page: return "No active page."
        try:
            if mode == "text":
                return self.page.inner_text("body")[:2000] # Cap for speech
            elif mode == "links":
                links = self.page.eval_on_selector_all("a", "elements => elements.map(e => e.href)")
                return ", ".join(list(set(links))[:10])
            elif mode == "tables":
                # Basic table extractor
                tables = self.page.query_selector_all("table")
                return f"Found {len(tables)} tables on the page."
            return "Unknown extraction mode."
        except Exception as e:
            return f"Extraction error: {e}"

    def get_summary(self, brain_instance) -> str:
        """Uses AI to summarize the current page content."""
        content = self.extract_page_data("text")
        return brain_instance.ask(f"Summarize this website content briefly: {content}")

    # GMAIL AUTOMATION (Simplified concept)
    def gmail_read_unread(self) -> str:
        self.navigate("https://mail.google.com")
        try:
            self.page.wait_for_selector("tr.zA.zE", timeout=10000) # Unread row
            subjects = self.page.eval_on_selector_all("tr.zA.zE span.bog", "elements => elements.map(e => e.innerText)")
            return f"You have {len(subjects)} unread emails. Recent subjects: {', '.join(subjects[:3])}"
        except:
            return "Could not detect unread emails. Are you logged in?"

    def _check_interruption(self):
        """Internal helper to stop actions if the user requested it."""
        if self.orchestrator and hasattr(self.orchestrator, 'stop_event'):
            if self.orchestrator.stop_event.is_set():
                raise Exception("Interrupted by user.")

    def _check_captcha(self):
        """Detects if a captcha/challenge is present on the page."""
        if not self.page: return
        selectors = [
            "iframe[src*='recaptcha']", "iframe[title*='reCAPTCHA']",
            ".g-recaptcha", "#captcha", "iframe[src*='hcaptcha']",
            "text='Verify you are human'", "text='Cloudflare'"
        ]
        for s in selectors:
            try:
                if self.page.locator(s).first.is_visible(timeout=500):
                    self.orchestrator.speak("Dhanush, I've detected a captcha challenge on the screen. Please solve it manually so I can proceed.")
                    # Wait up to 60s for it to disappear
                    for _ in range(60):
                        self._check_interruption()
                        if not self.page.locator(s).first.is_visible(timeout=1000):
                            self.orchestrator.speak("Challenge resolved. Continuing my task.")
                            return
                        time.sleep(1)
                    break
            except: pass

    def multi_tab_research(self, query: str, brain_instance) -> str:
        """Opens multiple tabs to research a topic and synthesizes a report."""
        if not self._ensure_session(): return "Failed to open browser for research."
        if hasattr(self, 'orchestrator') and self.orchestrator:
            self.orchestrator.speak(f"Starting multi-tab research on {query}...")

        try:
            # 1. Search Google/DuckDuckGo
            search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            
            # Extract top 3 links
            links = self.page.eval_on_selector_all("a.result__url", "elements => elements.map(e => e.href).filter(href => href && !href.includes('duckduckgo')).slice(0, 3)")
            
            if not links:
                return "I couldn't find any valid search results to research."

            # 2. Open tabs and extract content
            extracted_data = []
            for idx, link in enumerate(links):
                try:
                    if hasattr(self, 'orchestrator') and self.orchestrator:
                        self.orchestrator.speak(f"Reading source {idx+1}...")
                    
                    new_page = self.context.new_page()
                    new_page.goto(link, wait_until="domcontentloaded", timeout=10000)
                    
                    # Extract readable text
                    content = new_page.evaluate("""() => {
                        const article = document.querySelector('article') || document.body;
                        return article ? article.innerText.substring(0, 3000) : '';
                    }""")
                    
                    extracted_data.append(f"Source: {link}\nContent:\n{content}\n")
                    new_page.close()
                except Exception as e:
                    self.logger.warning(f"Failed to read source {link}: {e}")
                    if 'new_page' in locals() and not new_page.is_closed():
                        new_page.close()

            # 3. Synthesize Report
            if hasattr(self, 'orchestrator') and self.orchestrator:
                self.orchestrator.speak("Synthesizing research report...")
            
            combined_text = "\n---\n".join(extracted_data)
            prompt = (
                f"I am researching: '{query}'. "
                f"I have extracted information from multiple sources:\n\n{combined_text}\n\n"
                "Generate a detailed research report with the following markdown sections:\n"
                "## Executive Summary\n"
                "## Key Findings\n"
                "## Pros\n"
                "## Cons\n"
                "## Comparison / Analysis\n"
                "## References\n"
            )
            res = brain_instance.ask(prompt)
            if not res: return "I couldn't generate the research report."
            
            with open("flexie_research_report.md", "w", encoding="utf-8") as f:
                f.write(res)
            return f"I have finished researching {query}. A detailed comparative report has been saved to flexie_research_report.md."
            
        except Exception as e:
            return f"Research failed: {e}"

    def cleanup(self):
        """Safely terminates the browser session and playwright driver."""
        try:
            if self.page: self.page.close()
            if self.context: self.context.close()
            if self.playwright: self.playwright.stop()
            self.logger.info("Browser engine cleaned up successfully.")
        except Exception as e:
            # Silence EPIPE during exit as it is expected when Node driver is killed
            if "EPIPE" in str(e):
                self.logger.debug("Browser cleanup: Suppressed expected broken pipe.")
            else:
                self.logger.error(f"Browser cleanup error: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

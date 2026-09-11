import time
import threading
import logging
import urllib.parse
from engines.browser import BrowserEngine

class YouTubeController(BrowserEngine):
    """Advanced YouTube Automation inheriting from BrowserEngine."""
    def __init__(self, orchestrator=None):
        super().__init__(orchestrator)
        self.last_video_title = None
        self.last_query = None
        self._ad_monitor_active = False

    def is_session_active(self) -> bool:
        """Checks if there is an active YouTube session running. Thread-safe."""
        import threading
        if hasattr(self, "_thread_id") and self._thread_id != threading.get_ident():
            return False # Thread mismatch, session not 'active' for this caller
            
        try:
            return self.page is not None and not self.page.is_closed() and "youtube.com" in self.page.url
        except:
            return False

    def play_video(self, query: str) -> str:
        if not self._ensure_session(): return "Could not start browser."
        self.last_query = query
        
        try:
            self.navigate(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}")
            
            # Selector for the first video title
            video_selector = "ytd-video-renderer a#video-title"
            
            # Exponential Backoff Retry (Network Resilience)
            for attempt in range(3):
                try:
                    self.page.wait_for_selector(video_selector, timeout=20000)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise e
                    logging.warning(f"YouTube Timeout. Retrying ({attempt + 1}/3)...")
                    time.sleep(2)
            
            video = self.page.query_selector(video_selector)
            if video:
                full_title = video.inner_text().strip()
                # Shorten title: take only the part before the first pipe
                short_title = full_title.split("|")[0].strip()
                # If still too long, take first 40 chars
                if len(short_title) > 40:
                    short_title = short_title[:40].rsplit(" ", 1)[0]
                self.last_video_title = short_title
                video.click()
                
                return f"Now playing {short_title} on YouTube."
            return "Found the results but couldn't click the video."
        except Exception as e:
            return f"YouTube play error: {e}"

    # _ad_monitor_loop removed. 
    # STABILITY NOTE: Handled by Orchestrator's Action Worker to prevent Playwright threading crashes.

    def skip_ad(self) -> str:
        """The 'Nuke Mode' Ad Skipper. Uses direct DOM manipulation to click buttons and accelerate ads."""
        if not self._ensure_session(): return "No active session."
        try:
            # Aggressive JavaScript for the latest YT update
            status = self.page.evaluate('''() => {
                const video = document.querySelector('video');
                const ad = document.querySelector('.ad-showing, .ad-interrupting, .ytp-ad-player-overlay');
                
                // 1. Click any skip button (old and new UI)
                const skipSelectors = [
                    '.ytp-ad-skip-button', '.ytp-ad-skip-button-modern', 
                    '.ytp-skip-ad-button', '.ytp-ad-skip-button-text',
                    '.ytp-ad-skip-button-slot', '.ytp-ad-skip-button-container'
                ];
                
                for (let s of skipSelectors) {
                    let btn = document.querySelector(s);
                    if (btn && btn.offsetParent !== null) {
                        btn.click();
                        return "Button Clicked";
                    }
                }
                
                // 2. SPEED HACK for non-skippable ads
                if (ad && video) {
                    video.playbackRate = 16.0;
                    video.muted = true;
                    // If near end, jump to finish
                    if (video.duration - video.currentTime < 2) {
                        video.currentTime = video.duration - 0.1;
                    }
                    return "Ad Accelerated";
                }
                
                // 3. Clear Overlays
                document.querySelectorAll('.ytp-ad-overlay-close-button').forEach(el => el.click());
                
                return "Monitoring...";
            }''')
            
            if status in ["Button Clicked", "Ad Accelerated"]:
                self.logger.info(f"YouTube Ad Action: {status}")
                return f"YouTube {status}."
            return "No skippable ad detected."
        except Exception as e:
            return f"Ad action error: {e}"

    def control_player(self, action: str) -> str:
        """Handles advanced player controls including speed, modes, and navigation."""
        if not self._ensure_session(): return "No active YouTube session."
        try:
            self.page.focus("body")
            
            if action in ["pause", "resume", "play", "stop"]:
                self.page.keyboard.press("k"); return f"Video {action}ed."
            elif action == "next":
                self.page.keyboard.press("Shift+N"); return "Playing next."
            elif action == "mute":
                self.page.keyboard.press("m"); return "Muted."
            elif action == "fullscreen":
                self.page.keyboard.press("f"); return "Toggled fullscreen."
            elif action == "theatre":
                self.page.keyboard.press("t"); return "Toggled theatre mode."
            elif action == "captions":
                self.page.keyboard.press("c"); return "Toggled captions."
            elif action == "speed up":
                self.page.keyboard.press("Shift+."); return "Increased speed."
            elif action == "slow down":
                self.page.keyboard.press("Shift+,"); return "Decreased speed."
            elif action == "reset speed":
                self.page.evaluate("document.querySelector('video').playbackRate = 1.0"); return "Speed reset."
            elif action == "forward":
                self.page.keyboard.press("l"); return "Skipped 10 seconds forward."
            elif action == "backward":
                self.page.keyboard.press("j"); return "Skipped 10 seconds backward."
            elif action == "volume up":
                self.page.keyboard.press("ArrowUp"); return "Increased player volume."
            elif action == "volume down":
                self.page.keyboard.press("ArrowDown"); return "Decreased player volume."
            return "Unknown control."
        except Exception as e:
            return f"Control error: {e}"

    def get_video_info(self) -> str:
        if not self.page: return "No video is currently playing."
        try:
            title = self.page.inner_text("h1.ytd-watch-metadata").strip()
            return f"You are watching {title}."
        except:
            return "Could not retrieve video information."

    def play_again(self) -> str:
        if self.last_query:
            return self.play_video(self.last_query)
        return "I haven't searched for any videos yet."

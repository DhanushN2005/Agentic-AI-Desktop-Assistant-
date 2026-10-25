import logging
import queue
import threading
import time
import urllib.parse

from engines.browser import BrowserEngine


class YouTubeController(BrowserEngine):
    """Advanced YouTube Automation inheriting from BrowserEngine.

    All Playwright operations are dispatched to a single persistent worker thread
    (_yt_worker) that starts on construction and never exits.  This avoids the
    Playwright sync-API constraint that operations must run in the thread that
    called sync_playwright().start() — or at least in a thread whose greenlet
    context is still alive.
    """

    def __init__(self, orchestrator=None):
        super().__init__(orchestrator)
        self.last_video_title = None
        self.last_query = None
        self._ad_monitor_active = False

        self._task_queue: queue.Queue = queue.Queue()
        self._yt_thread = threading.Thread(
            target=self._yt_worker, daemon=True, name="flexie_yt_worker"
        )
        self._yt_thread.start()

    # ── persistent worker ────────────────────────────────────────────────────

    def _yt_worker(self):
        """Single long-lived thread that owns all Playwright calls."""
        time.sleep(3)  # let orchestrator finish startup
        try:
            self._ensure_session()
            self.logger.info("[YT Worker] Browser session pre-warmed and ready.")
        except Exception as e:
            self.logger.debug("[YT Worker] Pre-warm skipped: %s", e)

        while True:
            try:
                fn, holder = self._task_queue.get(timeout=120)
            except queue.Empty:
                continue
            try:
                holder["result"] = fn()
                holder["error"] = None
            except Exception as e:
                holder["result"] = None
                holder["error"] = e
            finally:
                holder["event"].set()

    def _run(self, fn, timeout: float = 45.0):
        """Submit fn() to the YT worker thread and block until it completes."""
        holder = {"result": None, "error": None, "event": threading.Event()}
        self._task_queue.put((fn, holder))
        if not holder["event"].wait(timeout=timeout):
            raise TimeoutError(f"YT worker did not complete within {timeout}s")
        if holder["error"]:
            raise holder["error"]
        return holder["result"]

    # ── public API (all dispatched to worker) ────────────────────────────────

    def is_session_active(self) -> bool:
        try:
            return self._run(self._session_active_impl, timeout=5.0)
        except Exception:
            return False

    def _session_active_impl(self) -> bool:
        try:
            return (
                self.page is not None
                and not self.page.is_closed()
                and "youtube.com" in self.page.url
            )
        except Exception:
            return False

    def play_video(self, query: str) -> str:
        return self._run(lambda: self._play_video_impl(query))

    def _play_video_impl(self, query: str) -> str:
        if not self._ensure_session():
            return "Could not start browser."
        self.last_query = query

        try:
            import urllib.request, re
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    html = response.read().decode("utf-8", errors="ignore")
                    video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", html)
                    if video_ids:
                        vid = video_ids[0]
                        title = query
                        m = re.search(r'"title":\{"runs":\[\{"text":"(.*?)"\}\]', html)
                        if m:
                            title = m.group(1).split("|")[0].strip()
                            if len(title) > 40:
                                title = title[:40].rsplit(" ", 1)[0]
                        self.last_video_title = title
                        self.navigate(f"https://www.youtube.com/watch?v={vid}")
                        if not self.page:
                            return "Browser page is closed or not available."
                        return f"Now playing {title} on YouTube."
            except Exception as e:
                logging.warning("Fast path failed, falling back to slow navigation: %s", e)

            # Fallback — navigate to search results page and click first video
            self.navigate(url)
            if not self.page:
                return "Browser page is closed or not available."

            video_selector = "ytd-video-renderer a#video-title"
            for attempt in range(3):
                try:
                    self.page.wait_for_selector(video_selector, timeout=20000)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise e
                    logging.warning("YouTube timeout. Retrying (%d/3)…", attempt + 1)
                    time.sleep(2)

            video = self.page.query_selector(video_selector)
            if video:
                full_title = video.inner_text().strip()
                short_title = full_title.split("|")[0].strip()
                if len(short_title) > 40:
                    short_title = short_title[:40].rsplit(" ", 1)[0]
                self.last_video_title = short_title
                video.click()
                return f"Now playing {short_title} on YouTube."
            return "Found the results but couldn't click the video."
        except Exception as e:
            logging.debug("[youtube_controller] play error: %s: %s", type(e).__name__, e)
            return f"YouTube play error: {e}"

    def skip_ad(self) -> str:
        return self._run(self._skip_ad_impl)

    def _skip_ad_impl(self) -> str:
        if not self._ensure_session():
            return "No active session."
        try:
            status = self.page.evaluate("""() => {
                const video = document.querySelector('video');
                const ad = document.querySelector('.ad-showing, .ad-interrupting, .ytp-ad-player-overlay');
                const skipSelectors = [
                    '.ytp-ad-skip-button', '.ytp-ad-skip-button-modern',
                    '.ytp-skip-ad-button', '.ytp-ad-skip-button-text',
                    '.ytp-ad-skip-button-slot', '.ytp-ad-skip-button-container'
                ];
                for (let s of skipSelectors) {
                    let btn = document.querySelector(s);
                    if (btn && btn.offsetParent !== null) { btn.click(); return "Button Clicked"; }
                }
                if (ad && video) {
                    video.playbackRate = 16.0; video.muted = true;
                    if (video.duration - video.currentTime < 2) video.currentTime = video.duration - 0.1;
                    return "Ad Accelerated";
                }
                document.querySelectorAll('.ytp-ad-overlay-close-button').forEach(el => el.click());
                return "Monitoring...";
            }""")
            if status in ("Button Clicked", "Ad Accelerated"):
                return f"YouTube {status}."
            return "No skippable ad detected."
        except Exception as e:
            logging.debug("[youtube_controller] skip_ad error: %s", e)
            return f"Ad action error: {e}"

    def control_player(self, action: str) -> str:
        return self._run(lambda: self._control_player_impl(action))

    def _control_player_impl(self, action: str) -> str:
        if not self._ensure_session():
            return "No active YouTube session."
        try:
            self.page.focus("body")
            if action in ("pause", "resume", "play", "stop"):
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
                self.page.evaluate("document.querySelector('video').playbackRate = 1.0")
                return "Speed reset."
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
            logging.debug("[youtube_controller] control error: %s", e)
            return f"Control error: {e}"

    def get_video_info(self) -> str:
        try:
            return self._run(self._get_video_info_impl, timeout=5.0)
        except Exception:
            return "No video is currently playing."

    def _get_video_info_impl(self) -> str:
        if not self.page:
            return "No video is currently playing."
        try:
            title = self.page.inner_text("h1.ytd-watch-metadata").strip()
            return f"You are watching {title}."
        except Exception:
            return "Could not retrieve video information."

    def play_again(self) -> str:
        if self.last_query:
            return self.play_video(self.last_query)
        return "I haven't searched for any videos yet."

    def cleanup(self):
        """Route browser cleanup through the worker thread to avoid greenlet cross-thread crash."""
        try:
            self._run(super().cleanup, timeout=5.0)
        except Exception as e:
            logging.debug("[youtube_controller] cleanup via worker failed (%s); forcing direct cleanup", e)
            try:
                super().cleanup()
            except Exception:
                pass

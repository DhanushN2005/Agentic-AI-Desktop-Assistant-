import logging
import os
import re
import subprocess
from ctypes import POINTER, cast

import psutil

# Platform-specific desktop libraries are optional: on non-Windows hosts (or headless CI)
# they fail to import, and the matching controls simply degrade instead of breaking import
# of the whole module (and with it the orchestrator).
try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except Exception as _e:
    logging.debug("[engines/system.py] pycaw/comtypes unavailable (Windows audio control disabled): %s", _e)
    CLSCTX_ALL = AudioUtilities = IAudioEndpointVolume = None

try:
    import screen_brightness_control as sbc
except Exception as _e:
    logging.debug("[engines/system.py:6] screen_brightness_control unavailable: %s", _e)
    sbc = None
from utils.helpers import is_online
from utils.lazy import LazyModule

pyautogui = LazyModule("pyautogui")  # imported on first use; falsy if unavailable

try:
    import pygetwindow as gw
except ImportError as _e:
    logging.debug("[engines/system.py:12] Swallowed exception: %s: %s", type(_e).__name__, _e)
    gw = None
try:
    import pyperclip
except ImportError as _e:
    logging.debug("[engines/system.py:16] Swallowed exception: %s: %s", type(_e).__name__, _e)
    pyperclip = None

class SystemCtrl:
    @staticmethod
    def get_clipboard() -> str:
        """Returns the current text in the clipboard."""
        try:
            return pyperclip.paste() if pyperclip else ""
        except Exception as _e:
            logging.debug("[engines/system.py:25] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return ""

    @staticmethod
    def set_clipboard(text: str):
        """Sets the clipboard text."""
        try:
            if pyperclip:
                pyperclip.copy(text)
        except Exception as _e:
            logging.debug("[engines/system.py:33] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass

    @staticmethod
    def _endpoint():
        """The default speakers' volume control, for old and new pycaw versions.

        pycaw 2024+ returns an ``AudioDevice`` wrapper that has ``.EndpointVolume`` and no ``.Activate``;
        older versions return the raw device. Calling ``.Activate`` on the new one raised AttributeError,
        which used to be swallowed, so every volume command silently did nothing."""
        if AudioUtilities is None:
            raise RuntimeError("pycaw is not installed")
        speakers = AudioUtilities.GetSpeakers()
        ready = getattr(speakers, "EndpointVolume", None)
        if ready is not None:
            return ready
        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    @staticmethod
    def _com(fn):
        """Run ``fn`` with COM initialised on this thread; returns (ok, value). Errors are logged, never hidden."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception as _e:
            logging.debug("CoInitialize skipped: %s", _e)
        try:
            return True, fn()
        except Exception as e:
            logging.warning("Windows volume control failed: %s: %s", type(e).__name__, e)
            return False, None
        finally:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception as _e:
                logging.debug("CoUninitialize skipped: %s", _e)

    @staticmethod
    def get_volume():
        """Current master volume 0-100, or None when Windows audio cannot be reached (never a made-up 50)."""
        ok, value = SystemCtrl._com(lambda: int(round(SystemCtrl._endpoint().GetMasterVolumeLevelScalar() * 100)))
        return value if ok else None

    @staticmethod
    def set_volume(level: int) -> bool:
        """Set master volume 0-100. Returns True only if Windows accepted it."""
        scalar = max(0, min(100, int(level))) / 100.0
        ok, _ = SystemCtrl._com(lambda: SystemCtrl._endpoint().SetMasterVolumeLevelScalar(scalar, None))
        return ok

    @staticmethod
    def get_mute():
        ok, value = SystemCtrl._com(lambda: bool(SystemCtrl._endpoint().GetMute()))
        return value if ok else None

    @staticmethod
    def set_mute(muted: bool) -> bool:
        ok, _ = SystemCtrl._com(lambda: SystemCtrl._endpoint().SetMute(1 if muted else 0, None))
        return ok

    @staticmethod
    def get_brightness():
        """Current screen brightness 0-100, or None when the display doesn't support it (desktop monitors often don't)."""
        try:
            value = sbc.get_brightness()
            value = value[0] if isinstance(value, (list, tuple)) else value
            return int(value)
        except Exception as _e:
            logging.debug("brightness read failed: %s: %s", type(_e).__name__, _e)
            return None

    @staticmethod
    def set_brightness(v):
        try:
            sbc.set_brightness(v)
        except Exception as _e:
            logging.debug("[engines/system.py:61] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass

    @staticmethod
    def power(action):
        table = {
            "shutdown": ["shutdown", "/s", "/t", "10"],
            "restart": ["shutdown", "/r", "/t", "10"],
            "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
            "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
        }
        for k, argv in table.items():
            if k in action.lower():
                try:
                    subprocess.Popen(argv, shell=False)
                except Exception as _e:
                    logging.debug("[engines/system.py:power] Swallowed exception: %s: %s", type(_e).__name__, _e)
                return

    @staticmethod
    def media(action):
        km = {
            "play": "playpause",
            "pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "mute": "volumemute"
        }
        if not pyautogui:
            logging.warning("Media keys need a desktop session (pyautogui unavailable).")
            return
        for k, v in km.items():
            if k in action.lower():
                pyautogui.press(v)
                return

    @staticmethod
    def wifi_status() -> str:
        if is_online():
            return "You are connected to the internet."
        for nic, stats in psutil.net_if_stats().items():
            if stats.isup and "wi" in nic.lower():
                return "Wi-Fi adapter is ON but no internet connection."
        return "Wi-Fi appears to be OFF."

    @staticmethod
    def cpu_ram():
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        return cpu, ram

    @staticmethod
    def battery_status():
        b = psutil.sensors_battery()
        if not b:
            return "--"
        return f"{b.percent}%"

    @staticmethod
    def save_active_file():
        """Sends Ctrl+S to the currently active window."""
        try:
            pyautogui.hotkey('ctrl', 's')
            return True
        except Exception as _e:
            logging.debug("[engines/system.py:118] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return False

    @staticmethod
    def get_active_window_title() -> str:
        """Returns the title of the active window."""
        try:
            if gw:
                win = gw.getActiveWindow()
                return win.title if win else "Unknown"
            return "Unknown"
        except Exception as _e:
            logging.debug("[engines/system.py:129] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return "Unknown"

    # Characters that let one string become several commands / redirect / expand.
    _CMD_META = re.compile(r"[&<>^%|;`\r\n\x00]|[$][(]")
    _DESTRUCTIVE_VERBS = frozenset({
        "rm", "del", "erase", "rd", "rmdir", "format", "fdisk", "diskpart", "shutdown", "restart",
        "poweroff", "move", "ren", "rename", "copy", "xcopy", "robocopy", "attrib", "reg", "regedit",
        "powershell", "pwsh", "wmic", "taskkill", "net", "sc", "cipher", "takeown", "icacls",
        "schtasks", "bcdedit", "mklink", "start", "call", "cmd", "curl", "wget", "certutil",
        "bitsadmin", "mshta", "rundll32",
    })
    _CMD_DESTRUCTIVE = re.compile(r"\b(?:rm\s+-rf|del\s+/[sq]|format|fdisk|shutdown|poweroff)\b|>\s*nul|2>\s*/dev", re.IGNORECASE)
    _SENSITIVE_NAME = re.compile(r"(^\.env|\.pem$|\.key$|\.pfx$|id_rsa|password|secret|credential|token)", re.IGNORECASE)

    @staticmethod
    def run_cmd(command: str) -> str:
        """Run one of a few read-only commands WITHOUT a shell.

        Only dir / cd / type / echo / cls / ver are accepted. Any shell
        metacharacter (& < > ^ % | ; backtick $( ) or newline) or destructive
        token is rejected, and nothing is ever passed to ``cmd /c`` as a string:
        the commands are executed in Python (or as a fixed argv for ``ver``).
        """
        command = (command or "").strip()
        if SystemCtrl._CMD_META.search(command):
            return "Security blocked: command chaining, redirection and special characters are not allowed."
        verb, _, rest = command.partition(" ")
        verb = verb.lower()
        rest = rest.strip()
        m = SystemCtrl._CMD_DESTRUCTIVE.search(command)
        if m or verb in SystemCtrl._DESTRUCTIVE_VERBS:
            return f"Security blocked: '{m.group(0) if m else verb}' command prevented."
        if verb not in ("dir", "cd", "type", "echo", "cls", "ver"):
            return "Command not allowed. Use: dir, cd, type, echo, cls, or ver commands only."
        try:
            if verb == "echo":
                return (rest or "ECHO is on.")[:500]
            if verb == "cls":
                return "Screen cleared."
            if verb == "ver":
                if os.name != "nt":
                    return "Command executed successfully (no output)."
                res = subprocess.run(["cmd.exe", "/c", "ver"], capture_output=True, text=True,
                                     timeout=10, shell=False)
                return (res.stdout.strip() or "Command executed successfully (no output).")[:500]
            target = rest.strip('"') or os.getcwd()
            if verb == "cd":
                return os.path.abspath(target) if os.path.isdir(target) else "The system cannot find the path specified."
            if verb == "dir":
                if not os.path.isdir(target):
                    return "File Not Found"
                names = sorted(os.listdir(target))[:50]
                return (", ".join(names) or "Directory is empty.")[:500]
            if verb == "type":
                if not os.path.isfile(target):
                    return "The system cannot find the file specified."
                if SystemCtrl._SENSITIVE_NAME.search(os.path.basename(target)):
                    return "Security blocked: that file looks like it holds secrets."
                with open(target, encoding="utf-8", errors="replace") as fh:
                    return fh.read(500)
        except Exception as e:
            return f"Command failed: {str(e)[:200]}"
        return "Command executed successfully (no output)."

    # Exact process-name aliases (never substring matching).
    _APP_ALIASES = {
        "chrome": ["chrome.exe"], "google chrome": ["chrome.exe"],
        "vscode": ["code.exe"], "vs code": ["code.exe"], "visual studio code": ["code.exe"],
        "spotify": ["spotify.exe"], "notepad": ["notepad.exe"],
        "calculator": ["calculatorapp.exe", "calc.exe", "calculator.exe"],
        "edge": ["msedge.exe"], "firefox": ["firefox.exe"], "brave": ["brave.exe"],
        "word": ["winword.exe"], "excel": ["excel.exe"], "powerpoint": ["powerpnt.exe"],
        "vlc": ["vlc.exe"], "discord": ["discord.exe"], "teams": ["teams.exe", "ms-teams.exe"],
        "whatsapp": ["whatsapp.exe", "whatsapp.root.exe"],
    }
    _PROTECTED_PROCESSES = frozenset({
        "system", "system idle process", "registry", "memcompression", "smss.exe", "csrss.exe",
        "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "explorer.exe",
        "dwm.exe", "fontdrvhost.exe", "spoolsv.exe", "taskhostw.exe", "sihost.exe", "ctfmon.exe",
        "searchhost.exe", "startmenuexperiencehost.exe", "runtimebroker.exe", "audiodg.exe",
        "msmpeng.exe", "securityhealthservice.exe", "conhost.exe", "lsm.exe", "wudfhost.exe",
        "python.exe", "pythonw.exe", "py.exe",
    })
    _ALL_WORDS = frozenset({"all", "everything", "all apps", "all applications", "all windows", "all programs", "all of them"})

    @staticmethod
    def _own_pids() -> set:
        pids = {os.getpid()}
        try:
            me = psutil.Process()
            pids.update(ch.pid for ch in me.children(recursive=True))
            pids.update(par.pid for par in me.parents())
        except Exception as _e:
            logging.debug("own pid discovery failed: %s", _e)
        return pids

    @staticmethod
    def is_close_all(app_name: str) -> bool:
        return (app_name or "").lower().strip() in SystemCtrl._ALL_WORDS

    @staticmethod
    def close_app(app_name: str) -> bool:
        """Terminate processes whose name EXACTLY equals the app (or a curated alias)."""
        target = (app_name or "").lower().replace(".exe", "").strip()
        if not target or SystemCtrl.is_close_all(target):
            return False
        names = {n.lower() for n in SystemCtrl._APP_ALIASES.get(target, [])}
        if re.fullmatch(r"[a-z0-9_.\- ]+", target):
            names.add(target + ".exe")
        names -= SystemCtrl._PROTECTED_PROCESSES
        if not names:
            return False
        own = SystemCtrl._own_pids()
        killed = False
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname in names and proc.info.get("pid") not in own:
                    proc.terminate()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied) as _e:
                logging.debug("close_app skip: %s: %s", type(_e).__name__, _e)
                continue
        return killed

    @staticmethod
    def app_process_names(app_name: str) -> set:
        """Executable names that count as ``app_name`` (the same rule close_app uses)."""
        target = (app_name or "").lower().replace(".exe", "").strip()
        if not target or SystemCtrl.is_close_all(target):
            return set()
        names = {n.lower() for n in SystemCtrl._APP_ALIASES.get(target, [])}
        if re.fullmatch(r"[a-z0-9_.\- ]+", target):
            names.add(target + ".exe")
        return names - SystemCtrl._PROTECTED_PROCESSES

    @staticmethod
    def list_app_windows(app_name: str) -> list:
        """Visible top-level windows of ``app_name`` as [{hwnd, title, pid}].

        Flexie's own windows and Flexie's own browser (profile ``browser_session``) are never listed,
        so "close chrome" can only ever offer the user's windows. Returns [] when unsupported."""
        names = SystemCtrl.app_process_names(app_name)
        if not names:
            return []
        try:
            import win32con
            import win32gui
            import win32process
        except ImportError:
            return []
        own = SystemCtrl._own_pids()
        out: list = []

        def _flexie_browser(pid: int) -> bool:
            try:
                return "browser_session" in " ".join(psutil.Process(pid).cmdline()).replace("\\", "/")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False

        def _cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                    return True
                if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
                    return True
                title = (win32gui.GetWindowText(hwnd) or "").strip()
                if not title:
                    return True
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid in own:
                    return True
                if (psutil.Process(pid).name() or "").lower() in names and not _flexie_browser(pid):
                    out.append({"hwnd": hwnd, "title": title, "pid": pid})
            except Exception as _e:
                logging.debug("list_app_windows skip: %s", _e)
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as _e:
            logging.debug("EnumWindows failed: %s", _e)
        return out

    @staticmethod
    def close_window(hwnd: int) -> bool:
        """Ask ONE window to close (WM_CLOSE, so the app can still offer to save). True if it was sent."""
        try:
            import win32con
            import win32gui
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return True
        except Exception as e:
            logging.debug("close_window failed: %s", e)
            return False

    @staticmethod
    def close_all_known_apps() -> list:
        """After explicit confirmation: close every running app from the curated alias list."""
        closed = []
        for app in ("chrome", "edge", "firefox", "spotify", "notepad", "vlc", "word", "excel", "powerpoint"):
            if SystemCtrl.close_app(app):
                closed.append(app)
        return closed

    @staticmethod
    def snap_window(direction: str, app_name: str = None) -> str:
        """Positions and snaps a window to a grid coordinate on the screen with focus verification."""
        if not gw:
            return "Window snapping is unavailable because pygetwindow is not installed."

        try:
            win = None
            if app_name:
                # Fuzzy matching in window titles
                app_target = app_name.lower().strip()
                all_wins = gw.getAllWindows()
                for w in all_wins:
                    if app_target in w.title.lower():
                        win = w
                        break
            if not win:
                win = gw.getActiveWindow()

            if not win:
                return "I couldn't locate any active window to snap."

            if not pyautogui:
                return "Window snapping needs a desktop session."
            # Get screen resolution
            screen_w, screen_h = pyautogui.size()
            direction = direction.lower().strip()

            # Maximize/Restore if minimized
            if win.isMinimized:
                win.restore()

            # Focus/Activation verification loop (Priority 1 & 6)
            import time
            focused = False
            for _ in range(3):
                try:
                    win.activate()
                    time.sleep(0.15)
                    active_win = gw.getActiveWindow()
                    if active_win and active_win._hWnd == win._hWnd:
                        focused = True
                        break
                except Exception as _e:
                    logging.debug("[engines/system.py:202] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    pass

                # Tap ALT key as a self-healing fallback to release Windows foreground lock
                try:
                    pyautogui.press('alt')
                except Exception as _e:
                    logging.debug("[engines/system.py:208] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    pass
                time.sleep(0.15)

            if not focused:
                logging.debug("[engines/system.py] snap_window: could not confirm focus after 3 attempts")
            if "left" in direction:
                win.restore()
                win.resizeTo(screen_w // 2, screen_h - 40) # Subtract 40px for taskbar safety
                win.moveTo(0, 0)
                return f"Snapped '{win.title[:20]}...' to the left half."
            elif "right" in direction:
                win.restore()
                win.resizeTo(screen_w // 2, screen_h - 40)
                win.moveTo(screen_w // 2, 0)
                return f"Snapped '{win.title[:20]}...' to the right half."
            elif "top" in direction or "up" in direction:
                win.restore()
                win.resizeTo(screen_w, screen_h // 2)
                win.moveTo(0, 0)
                return f"Snapped '{win.title[:20]}...' to the top half."
            elif "bottom" in direction or "down" in direction:
                win.restore()
                win.resizeTo(screen_w, (screen_h - 40) // 2)
                win.moveTo(0, screen_h // 2)
                return f"Snapped '{win.title[:20]}...' to the bottom half."
            elif "full" in direction or "max" in direction:
                win.maximize()
                return f"Maximized '{win.title[:20]}...'."
            elif "minimize" in direction or "hide" in direction:
                win.minimize()
                return f"Minimized '{win.title[:20]}...'."
            else:
                return f"Unknown snap direction '{direction}'."
        except Exception as e:
            logging.debug("[engines/system.py:240] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"Failed to snap window: {e}"

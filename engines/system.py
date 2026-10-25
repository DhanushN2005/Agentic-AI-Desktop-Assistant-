import psutil
import pyautogui
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import screen_brightness_control as sbc
from utils.helpers import is_online
import logging
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
            if pyperclip: pyperclip.copy(text)
        except Exception as _e:
            logging.debug("[engines/system.py:33] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass

    @staticmethod
    def set_volume(level: int):
        try:
            db_volume = max(0, min(100, level)) / 100.0
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(db_volume, None)
        except Exception as _e:
            logging.debug("[engines/system.py:44] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass

    @staticmethod
    def get_volume() -> int:
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            return int(volume.GetMasterVolumeLevelScalar() * 100)
        except Exception as _e:
            logging.debug("[engines/system.py:54] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return 50

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
                    import subprocess
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
        if not b: return "--"
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

    @staticmethod
    def run_cmd(command: str) -> str:
        """Execute a CMD command with safety restrictions.
        
        Blocks destructive commands for security.
        Returns the output or error message."""
        import subprocess
        
        # Security: Block destructive commands
        destructive = [
            "rm -rf", "del /s", "format", "fdisk",
            "shutdown", "restart", "poweroff",
            ">null", ">>null", ">/dev", "2>/dev"
        ]
        
        cmd_lower = command.lower().strip()
        for d in destructive:
            if d in cmd_lower:
                return f"Security blocked: '{d}' command prevented."
        
        # Only allow specific safe commands
        safe_prefixes = ["dir ", "cd ", "type ", "echo ", "cls ", "ver "]
        if not any(cmd_lower.startswith(p) for p in safe_prefixes):
            return "Command not allowed. Use: dir, cd, type, echo, cls, or ver commands only."
        
        try:
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                timeout=10,
                shell=False
            )
            output = result.stdout.strip()
            error = result.stderr.strip()
            
            if output:
                return output[:500]  # Limit output length
            elif error:
                return f"Error: {error[:200]}"
            else:
                return "Command executed successfully (no output)."
        except subprocess.TimeoutExpired:
            return "Command timed out (10s limit)."
        except Exception as e:
            return f"Command failed: {str(e)[:200]}"

    @staticmethod
    def close_app(app_name: str) -> bool:
        target = app_name.lower().replace(".exe", "").strip()
        if not target:
            return False
        
        killed = False
        app_map = {
            "chrome": ["chrome.exe"],
            "vscode": ["code.exe"],
            "vs code": ["code.exe"],
            "spotify": ["spotify.exe"],
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "edge": ["msedge.exe"]
        }
        
        process_names = app_map.get(target, [target if target.endswith(".exe") else target + ".exe", target])
        
        for proc in psutil.process_iter(['name', 'pid']):
            try:
                pname = proc.info['name'].lower()
                if any(tn in pname for tn in process_names) or target == pname.replace(".exe", ""):
                    proc.terminate()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied) as _e:
                logging.debug("[engines/system.py:157] Swallowed exception: %s: %s", type(_e).__name__, _e)
                continue
        return killed

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

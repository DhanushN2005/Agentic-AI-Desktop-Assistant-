"""Launcher helpers: web-bridge supervision, global hotkey and tray icon.

The desktop UI is the Qt floating-orb HUD (``interface/ui.py``), started by ``main.py``. This module
is the helper the rest of Flexie uses to reach the WEB dashboard (http://localhost:8766/) on request:
  * ``ensure_bridge`` / ``stop_bridge`` / ``open_dashboard`` start the bridge once (tracked, never
    orphaned) and open the page - used by "open web ui" and "open vision mode";
  * the ``Launcher`` class (global hotkey, default Ctrl+Alt+F via ``FLEXIE_HOTKEY``, and a tray
    icon) is optional and is NOT started by ``main.py``: the Qt HUD already has its own tray and
    hotkey, and two tray icons would be confusing.

Everything here is fail-soft: with no pywin32, no desktop session or a taken hotkey, Flexie keeps
running and says why in the log.
"""
from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_ui_bridge.py")
BRIDGE_HTTP_PORT = 8766   # keep in sync with web_ui_bridge.HTTP_PORT (a test enforces it)
BRIDGE_WS_PORT = 8765
ASSISTANT_UDP_PORT = 9887
DASHBOARD_URL = f"http://localhost:{BRIDGE_HTTP_PORT}/"
ORB_URL = DASHBOARD_URL + "#orb"
DEFAULT_HOTKEY = "ctrl+alt+f"

_log = logging.getLogger("Flexie.Launcher")

# ── hotkey spec ────────────────────────────────────────────────────────────────
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN}
_NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "home": 0x24, "end": 0x23,
               "insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22}


def parse_hotkey(spec: str | None) -> tuple[int, int] | None:
    """'ctrl+alt+f' -> (modifier flags, virtual-key code); None when the spec is unusable.

    At least one modifier is required: a bare letter would steal that key from every app.
    """
    parts = [p for p in (spec or "").lower().replace(" ", "").split("+") if p]
    if len(parts) < 2:
        return None
    key, mods = parts[-1], parts[:-1]
    flags = 0
    for m in mods:
        if m not in _MODS:
            return None
        flags |= _MODS[m]
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    else:
        return None
    return flags, vk


# ── web bridge supervision ─────────────────────────────────────────────────────
_bridge_proc: subprocess.Popen | None = None
_bridge_lock = threading.Lock()
_cleanup_registered = False


def bridge_alive(port: int = BRIDGE_HTTP_PORT, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _bridge_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--bridge"]
    return [sys.executable, BRIDGE_SCRIPT]


def ensure_bridge(wait: float = 6.0) -> bool:
    """Make sure the dashboard bridge is up: reuse a running one, else start it once.

    The child gets this run's UDP token (otherwise its relayed commands are rejected) and
    ``FLEXIE_BRIDGE_NO_BROWSER=1`` (opening the page is the caller's decision). Returns True
    when the HTTP port answers within ``wait`` seconds.
    """
    global _bridge_proc, _cleanup_registered
    with _bridge_lock:
        if bridge_alive():
            return True
        if _bridge_proc is not None and _bridge_proc.poll() is None:
            pass  # started by us a moment ago, still coming up
        else:
            env = os.environ.copy()
            env["FLEXIE_BRIDGE_NO_BROWSER"] = "1"
            if not env.get("FLEXIE_UDP_TOKEN"):
                try:
                    from utils.udp_auth import get_token
                    env["FLEXIE_UDP_TOKEN"] = get_token()
                except Exception as e:
                    _log.error("bridge token unavailable: %s: %s", type(e).__name__, e)
            try:
                _bridge_proc = subprocess.Popen(_bridge_command(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                stdin=subprocess.DEVNULL, env=env, cwd=_ROOT)
            except OSError as e:
                _log.error("could not start the web bridge: %s", e)
                return False
            if not _cleanup_registered:
                atexit.register(stop_bridge)
                _cleanup_registered = True
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if bridge_alive():
            return True
        time.sleep(0.2)
    return False


def stop_bridge() -> bool:
    """Stop the bridge this process started (a bridge started by hand is left alone)."""
    global _bridge_proc
    with _bridge_lock:
        proc, _bridge_proc = _bridge_proc, None
    if proc is None or proc.poll() is not None:
        return False
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception as e:
            _log.debug("bridge kill failed: %s", e)
    return True


def stop_any_bridge() -> bool:
    """Stop the dashboard bridge no matter who started it (this process, or the Qt HUD).

    Only a process that LISTENS on the bridge port and whose command line is our web_ui_bridge.py is
    ever terminated. Returns True if something was stopped.
    """
    stopped = stop_bridge()
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN or conn.laddr.port not in (BRIDGE_HTTP_PORT, BRIDGE_WS_PORT) or not conn.pid:
                continue
            try:
                proc = psutil.Process(conn.pid)
                cmd = " ".join(proc.cmdline()).replace("\\", "/")
                if "web_ui_bridge" not in cmd:
                    continue
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                _log.debug("bridge stop skipped: %s", e)
    except Exception as e:
        _log.debug("stop_any_bridge: %s", e)
    return stopped


def open_dashboard(url: str = DASHBOARD_URL, block: bool = False) -> bool | None:
    """Start the bridge if needed, then open ``url`` in the default browser.

    Non-blocking by default (the hotkey and tray callbacks must return at once).
    """
    def _go() -> bool:
        if not ensure_bridge():
            _log.error("web dashboard is not reachable on port %s", BRIDGE_HTTP_PORT)
            return False
        return bool(webbrowser.open(url))
    if block:
        return _go()
    threading.Thread(target=_go, name="open-dashboard", daemon=True).start()
    return None


def send_to_assistant(message: str) -> bool:
    """Send one signed command to the orchestrator (used by the tray's Wake item)."""
    try:
        from utils.udp_auth import pack
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(pack(message).encode("utf-8"), ("127.0.0.1", ASSISTANT_UDP_PORT))
        return True
    except Exception as e:
        _log.error("could not reach the assistant: %s: %s", type(e).__name__, e)
        return False


# ── hotkey + tray (Windows, pywin32) ───────────────────────────────────────────
WM_USER_TRAY = 0x0400 + 20
ID_OPEN, ID_ORB, ID_WAKE, ID_QUIT = 1001, 1002, 1003, 1004
HOTKEY_ID = 0x1F1E


def _make_icon_file() -> str | None:
    """Draw the tray icon (blue orb with an F) into a temp .ico; None if PIL is unavailable."""
    try:
        import tempfile

        from PIL import Image, ImageDraw
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, size - 4, size - 4), fill=(0, 100, 255, 255), outline=(0, 210, 255, 255), width=3)
        d.rectangle((24, 18, 28, 46), fill="white")
        d.rectangle((24, 18, 42, 22), fill="white")
        d.rectangle((24, 30, 38, 34), fill="white")
        path = os.path.join(tempfile.gettempdir(), "flexie_tray.ico")
        img.save(path, format="ICO", sizes=[(32, 32), (64, 64)])
        return path
    except Exception as e:
        _log.debug("tray icon drawing failed: %s", e)
        return None


class Launcher:
    """Owns the hotkey + tray thread. ``start()`` never raises and never blocks."""

    def __init__(self, on_quit=None, hotkey: str | None = None, enable_tray: bool = True):
        self.on_quit = on_quit
        self.hotkey_spec = hotkey or os.getenv("FLEXIE_HOTKEY") or DEFAULT_HOTKEY
        self.enable_tray = enable_tray
        self.hwnd = None
        self.hotkey_ok = False
        self.tray_ok = False
        self._thread: threading.Thread | None = None
        self._win32 = None

    def start(self) -> None:
        if sys.platform != "win32":
            _log.info("launcher: hotkey and tray are Windows-only; running headless")
            return
        self._thread = threading.Thread(target=self._safe_loop, name="flexie-launcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Close the hidden window (removes the tray icon and hotkey) and stop our bridge."""
        try:
            if self.hwnd and self._win32:
                self._win32[0].PostMessage(self.hwnd, self._win32[1].WM_CLOSE, 0, 0)
        except Exception as e:
            _log.debug("launcher stop: %s", e)
        stop_bridge()

    # -- internals -------------------------------------------------------------
    def _safe_loop(self) -> None:
        try:
            self._win_loop()
        except Exception as e:
            _log.warning("launcher stopped (%s: %s); Flexie keeps running without hotkey/tray", type(e).__name__, e)

    def _register_hotkey(self, win32gui) -> bool:
        spec = parse_hotkey(self.hotkey_spec)
        if spec is None:
            _log.warning("FLEXIE_HOTKEY %r is not valid (use e.g. ctrl+alt+f); no hotkey registered", self.hotkey_spec)
            return False
        flags, vk = spec
        try:
            win32gui.RegisterHotKey(self.hwnd, HOTKEY_ID, flags | MOD_NOREPEAT, vk)
            _log.info("global hotkey %s opens the dashboard", self.hotkey_spec)
            return True
        except Exception as e:
            _log.warning("hotkey %s is unavailable (%s); use the tray icon or say 'open web ui'", self.hotkey_spec, e)
            return False

    def _add_tray(self, win32gui, win32con) -> bool:
        try:
            icon = None
            path = _make_icon_file()
            if path:
                try:
                    icon = win32gui.LoadImage(0, path, win32con.IMAGE_ICON, 0, 0, win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
                except Exception as e:
                    _log.debug("tray icon load failed: %s", e)
            if icon is None:
                icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (self.hwnd, 1, flags, WM_USER_TRAY, icon, "Flexie"))
            return True
        except Exception as e:
            _log.warning("tray icon unavailable (%s); continuing without it", e)
            return False

    def _show_menu(self, win32gui, win32con) -> None:
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_OPEN, "Open Flexie")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_ORB, "Open Orb (vision mode)")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_WAKE, "Wake Flexie")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, ID_QUIT, "Quit")
        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos[0], pos[1], 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def _quit(self) -> None:
        if self.on_quit:
            threading.Thread(target=self.on_quit, name="flexie-quit", daemon=True).start()

    def _win_loop(self) -> None:
        import win32api
        import win32con
        import win32gui
        self._win32 = (win32gui, win32con)

        def on_hotkey(hwnd, msg, wparam, lparam):
            open_dashboard()
            return 0

        def on_tray(hwnd, msg, wparam, lparam):
            try:
                if lparam == win32con.WM_LBUTTONDBLCLK:
                    open_dashboard()
                elif lparam == win32con.WM_RBUTTONUP:
                    self._show_menu(win32gui, win32con)
            except Exception as e:
                _log.debug("tray event failed: %s", e)
            return 0

        def on_command(hwnd, msg, wparam, lparam):
            cmd = wparam & 0xFFFF
            if cmd == ID_OPEN:
                open_dashboard()
            elif cmd == ID_ORB:
                open_dashboard(ORB_URL)
            elif cmd == ID_WAKE:
                send_to_assistant("wake up")
            elif cmd == ID_QUIT:
                self._quit()
            return 0

        def on_close(hwnd, msg, wparam, lparam):
            win32gui.DestroyWindow(hwnd)
            return 0

        def on_destroy(hwnd, msg, wparam, lparam):
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 1))
            except Exception as e:
                _log.debug("tray delete failed: %s", e)
            try:
                win32gui.UnregisterHotKey(hwnd, HOTKEY_ID)
            except Exception as e:
                _log.debug("hotkey unregister failed: %s", e)
            win32gui.PostQuitMessage(0)
            return 0

        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "FlexieLauncherWindow"
        wc.lpfnWndProc = {win32con.WM_HOTKEY: on_hotkey, WM_USER_TRAY: on_tray, win32con.WM_COMMAND: on_command,
                          win32con.WM_CLOSE: on_close, win32con.WM_DESTROY: on_destroy}
        try:
            atom = win32gui.RegisterClass(wc)
        except Exception:
            atom = wc.lpszClassName  # already registered by an earlier Launcher in this process
        self.hwnd = win32gui.CreateWindow(atom, "Flexie", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None)
        self.hotkey_ok = self._register_hotkey(win32gui)
        self.tray_ok = self._add_tray(win32gui, win32con) if self.enable_tray else False
        win32gui.PumpMessages()

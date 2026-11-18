"""
Desktop Control — safe abstraction for general desktop interaction.

Provides a centralized, permission-controlled interface for:
  - screenshot capture
  - screen inspection
  - mouse click / double-click
  - keyboard input / hotkeys
  - scrolling
  - window selection / application switching
  - clipboard operations

EVERY public action passes through the permission system with an explicit ToolSpec-like
subject (name, tags, permission), so the untrusted-content (taint) rule applies and the
gate never has to guess a level from wording. Keystrokes that can execute things (Win-key
combos, Enter, Alt+F4, Ctrl+Alt+Del, newlines in typed text...) need USER_CONFIRMATION.
"""
import logging
import math
import os
import time

from core.action_result import ActionResult
from core.permission_system import PermissionSystem
from core.tool_registry import PermissionLevel, ToolSpec

MAX_WAIT_SECONDS = 30.0
MAX_TYPE_CHARS = 5000
MAX_SCROLL = 2000
_BUTTONS = frozenset({"left", "right", "middle"})

_KEY_ALIASES = {
    "windows": "win", "winleft": "win", "winright": "win", "cmd": "win", "command": "win",
    "super": "win", "control": "ctrl", "ctrlleft": "ctrl", "ctrlright": "ctrl",
    "altleft": "alt", "altright": "alt", "shiftleft": "shift", "shiftright": "shift",
    "delete": "del", "escape": "esc", "return": "enter",
}


def _norm_key(key: str) -> str:
    k = str(key).strip().lower()
    return _KEY_ALIASES.get(k, k)


def _spec(name: str, permission: PermissionLevel, *tags: str) -> ToolSpec:
    return ToolSpec(name=name, description=name, params=[], permission=permission,
                    execute_fn=lambda: None, tags=list(tags))


_R, _S, _U = PermissionLevel.READ_ONLY, PermissionLevel.SAFE_ACTION, PermissionLevel.USER_CONFIRMATION
# One explicit, tagged subject per action. Effectful actions carry "desktop"/"automation" tags
# (NOT the read-only tags) so the permission system's taint rule upgrades them to
# USER_CONFIRMATION once untrusted content entered the turn.
_SPECS: dict[str, ToolSpec] = {
    s.name: s for s in (
        _spec("desktop.screenshot", _R, "vision", "desktop"),
        _spec("desktop.screen_size", _R, "desktop"),
        _spec("desktop.pixel_color", _R, "vision", "desktop"),
        _spec("desktop.mouse_position", _R, "desktop"),
        _spec("desktop.active_window", _R, "desktop"),
        _spec("desktop.list_windows", _R, "desktop"),
        _spec("desktop.wait", _R, "desktop"),
        _spec("desktop.click", _S, "desktop", "automation"),
        _spec("desktop.double_click", _S, "desktop", "automation"),
        _spec("desktop.move_mouse", _S, "desktop", "automation"),
        _spec("desktop.scroll", _S, "desktop", "automation"),
        _spec("desktop.type", _S, "desktop", "automation"),
        _spec("desktop.press", _S, "desktop", "automation"),
        _spec("desktop.hotkey", _S, "desktop", "automation"),
        _spec("desktop.key_down", _S, "desktop", "automation"),
        _spec("desktop.key_up", _S, "desktop", "automation"),
        _spec("desktop.focus", _S, "desktop", "automation"),
        _spec("desktop.clipboard_copy", _S, "desktop", "clipboard"),
        _spec("desktop.clipboard_paste", _S, "desktop", "clipboard"),
        _spec("desktop.clipboard_clear", _S, "desktop", "clipboard"),
        _spec("desktop.close_window", _U, "desktop", "automation"),
        # Same actions when the keystroke could execute something.
        _spec("desktop.type_exec", _U, "desktop", "automation"),
        _spec("desktop.press_exec", _U, "desktop", "automation"),
        _spec("desktop.hotkey_exec", _U, "desktop", "automation"),
        _spec("desktop.key_down_exec", _U, "desktop", "automation"),
    )
}


def keys_can_execute(keys) -> bool:
    """True when pressing these keys together could launch/kill/run something."""
    ks = {_norm_key(k) for k in keys}
    if "win" in ks or "apps" in ks:
        return True  # Win+R, Win+X, Win+E, Start menu typing...
    if "enter" in ks:
        return True  # runs whatever is focused / typed
    if {"alt", "f4"} <= ks or {"ctrl", "alt", "del"} <= ks or {"ctrl", "shift", "esc"} <= ks:
        return True
    if "f4" in ks and "alt" in ks:
        return True
    return False


class DesktopControl:
    """
    Safe, centralized desktop interaction controller.

    All desktop actions (mouse, keyboard, screen) go through this module.
    Each action checks permissions before execution.
    """

    def __init__(self, permission_system: PermissionSystem | None = None):
        self.permissions = permission_system or PermissionSystem()
        self.logger = logging.getLogger("Flexie.DesktopControl")
        self._pyautogui = None
        self._pyperclip = None
        # Path only: the folder is created lazily on the first screenshot, never at construction.
        self._screenshot_dir = os.path.join(os.path.expanduser("~"), "Desktop", "flexie_screenshots")
        self._held_keys: set[str] = set()
        self._screen: tuple[int, int] | None = None

    # --- helpers ---
    def _gate(self, action: str, intent: str) -> ActionResult | None:
        """Run the permission check for ``action`` (a key of _SPECS). None => allowed."""
        allowed, reason, _ = self.permissions.check_permission(_SPECS[action])
        if not allowed:
            return ActionResult.fail(message=reason, intent=intent, data={"permission_denied": True})
        return None

    def _get_pyautogui(self):
        if self._pyautogui is None:
            try:
                import pyautogui
                pyautogui.FAILSAFE = True
                pyautogui.PAUSE = 0.1
                self._pyautogui = pyautogui
            except ImportError as err:
                raise RuntimeError("pyautogui not installed") from err
        return self._pyautogui

    def _get_pyperclip(self):
        if self._pyperclip is None:
            try:
                import pyperclip
                self._pyperclip = pyperclip
            except ImportError as err:
                raise RuntimeError("pyperclip not installed") from err
        return self._pyperclip

    def _screen_size(self) -> tuple[int, int]:
        if self._screen is None:
            w, h = self._get_pyautogui().size()
            self._screen = (int(w), int(h))
        return self._screen

    @staticmethod
    def _num(value, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        return value

    def _check_xy(self, x, y) -> tuple[int, int]:
        """Coordinates must be numbers that lie on the screen."""
        x = int(self._num(x, "x"))
        y = int(self._num(y, "y"))
        w, h = self._screen_size()
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"coordinates ({x}, {y}) are outside the {w}x{h} screen")
        return x, y

    def _combo_executes(self, keys) -> bool:
        return keys_can_execute(set(keys) | self._held_keys)

    # --- SCREEN OPERATIONS ---

    def screenshot(self, region: tuple[int, int, int, int] | None = None) -> ActionResult:
        """Take a screenshot. Returns path to saved image."""
        denied = self._gate("desktop.screenshot", "screenshot")
        if denied is not None:
            return denied

        try:
            pag = self._get_pyautogui()
            if region is not None:
                if len(region) != 4:
                    raise ValueError("region must be (left, top, width, height)")
                left, top, width, height = (int(self._num(v, "region")) for v in region)
                sw, sh = self._screen_size()
                if width <= 0 or height <= 0 or left < 0 or top < 0 or left + width > sw or top + height > sh:
                    raise ValueError(f"region is outside the {sw}x{sh} screen")
                region = (left, top, width, height)
            os.makedirs(self._screenshot_dir, exist_ok=True)
            timestamp = int(time.time())
            path = os.path.join(self._screenshot_dir, f"screenshot_{timestamp}.png")
            img = pag.screenshot(region=region) if region else pag.screenshot()
            img.save(path)
            self.logger.info(f"[DESKTOP] Screenshot saved: {path}")
            return ActionResult.ok(message=path, intent="screenshot", data={"path": path})
        except Exception as e:
            logging.debug("[core/desktop_control.py] screenshot: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="screenshot")

    def get_screen_size(self) -> ActionResult:
        """Get screen dimensions."""
        denied = self._gate("desktop.screen_size", "screen_size")
        if denied is not None:
            return denied
        try:
            pag = self._get_pyautogui()
            w, h = pag.size()
            return ActionResult.ok(
                message=f"{w}x{h}",
                intent="screen_size",
                data={"width": w, "height": h}
            )
        except Exception as e:
            logging.debug("[core/desktop_control.py] screen_size: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="screen_size")

    def get_pixel_color(self, x: int, y: int) -> ActionResult:
        """Get the color of a pixel at (x, y)."""
        denied = self._gate("desktop.pixel_color", "pixel_color")
        if denied is not None:
            return denied
        try:
            x, y = self._check_xy(x, y)
            pag = self._get_pyautogui()
            screenshot = pag.screenshot(region=(x, y, 1, 1))
            pixel = screenshot.getpixel((0, 0))
            hex_color = "#{:02x}{:02x}{:02x}".format(*pixel[:3])
            return ActionResult.ok(
                message=hex_color,
                intent="pixel_color",
                data={"r": pixel[0], "g": pixel[1], "b": pixel[2], "hex": hex_color}
            )
        except Exception as e:
            logging.debug("[core/desktop_control.py] pixel_color: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="pixel_color")

    # --- MOUSE OPERATIONS ---

    def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        """Click at position (x, y)."""
        denied = self._gate("desktop.click", "click")
        if denied is not None:
            return denied

        try:
            if button not in _BUTTONS:
                raise ValueError(f"button must be one of {sorted(_BUTTONS)}")
            x, y = self._check_xy(x, y)
            pag = self._get_pyautogui()
            pag.click(x, y, button=button)
            self.logger.info(f"[DESKTOP] Click at ({x}, {y}) button={button}")
            return ActionResult.ok(message=f"Clicked ({x}, {y})", intent="click")
        except Exception as e:
            logging.debug("[core/desktop_control.py] click: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="click")

    def double_click(self, x: int, y: int) -> ActionResult:
        """Double-click at position (x, y)."""
        denied = self._gate("desktop.double_click", "double_click")
        if denied is not None:
            return denied

        try:
            x, y = self._check_xy(x, y)
            pag = self._get_pyautogui()
            pag.doubleClick(x, y)
            self.logger.info(f"[DESKTOP] Double-click at ({x}, {y})")
            return ActionResult.ok(message=f"Double-clicked ({x}, {y})", intent="double_click")
        except Exception as e:
            logging.debug("[core/desktop_control.py] double_click: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="double_click")

    def move_mouse(self, x: int, y: int, duration: float = 0.3) -> ActionResult:
        """Move mouse to (x, y)."""
        denied = self._gate("desktop.move_mouse", "move_mouse")
        if denied is not None:
            return denied
        try:
            x, y = self._check_xy(x, y)
            duration = min(max(float(self._num(duration, "duration")), 0.0), 10.0)
            pag = self._get_pyautogui()
            pag.moveTo(x, y, duration=duration)
            return ActionResult.ok(message=f"Moved to ({x}, {y})", intent="move_mouse")
        except Exception as e:
            logging.debug("[core/desktop_control.py] move_mouse: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="move_mouse")

    def get_mouse_position(self) -> ActionResult:
        """Get current mouse position."""
        denied = self._gate("desktop.mouse_position", "mouse_pos")
        if denied is not None:
            return denied
        try:
            pag = self._get_pyautogui()
            x, y = pag.position()
            return ActionResult.ok(
                message=f"({x}, {y})",
                intent="mouse_pos",
                data={"x": x, "y": y}
            )
        except Exception as e:
            logging.debug("[core/desktop_control.py] mouse_pos: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="mouse_pos")

    def scroll(self, amount: int, x: int | None = None, y: int | None = None) -> ActionResult:
        """Scroll by amount (positive = up, negative = down)."""
        denied = self._gate("desktop.scroll", "scroll")
        if denied is not None:
            return denied

        try:
            amount = int(self._num(amount, "amount"))
            if abs(amount) > MAX_SCROLL:
                raise ValueError(f"scroll amount must be within +/-{MAX_SCROLL}")
            pag = self._get_pyautogui()
            if x is not None and y is not None:
                x, y = self._check_xy(x, y)
                pag.scroll(amount, x=x, y=y)
            else:
                pag.scroll(amount)
            direction = "up" if amount > 0 else "down"
            self.logger.info(f"[DESKTOP] Scrolled {direction} by {abs(amount)}")
            return ActionResult.ok(message=f"Scrolled {direction}", intent="scroll")
        except Exception as e:
            logging.debug("[core/desktop_control.py] scroll: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="scroll")

    # --- KEYBOARD OPERATIONS ---

    def type_text(self, text: str, interval: float = 0.02) -> ActionResult:
        """Type text character by character."""
        if not isinstance(text, str):
            return ActionResult.fail(message="text must be a string", intent="type_text")
        executes = ("\n" in text) or ("\r" in text) or bool(self._held_keys & {"win", "ctrl", "alt"})
        denied = self._gate("desktop.type_exec" if executes else "desktop.type", "type_text")
        if denied is not None:
            return denied

        try:
            if len(text) > MAX_TYPE_CHARS:
                raise ValueError(f"text is too long (max {MAX_TYPE_CHARS} chars)")
            interval = min(max(float(self._num(interval, "interval")), 0.0), 1.0)
            pag = self._get_pyautogui()
            pag.typewrite(text, interval=interval) if text.isascii() else pag.write(text)
            self.logger.info(f"[DESKTOP] Typed {len(text)} chars")  # never log the typed content
            return ActionResult.ok(message=f"Typed {len(text)} chars", intent="type_text")
        except Exception as e:
            logging.debug("[core/desktop_control.py] type_text: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="type_text")

    def press_key(self, key: str) -> ActionResult:
        """Press a single key."""
        if not isinstance(key, str) or not key.strip():
            return ActionResult.fail(message="key must be a non-empty string", intent="press_key")
        denied = self._gate("desktop.press_exec" if self._combo_executes([key]) else "desktop.press", "press_key")
        if denied is not None:
            return denied

        try:
            pag = self._get_pyautogui()
            pag.press(key)
            self.logger.info(f"[DESKTOP] Pressed: {key}")
            return ActionResult.ok(message=f"Pressed {key}", intent="press_key")
        except Exception as e:
            logging.debug("[core/desktop_control.py] press_key: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="press_key")

    def hotkey(self, *keys: str) -> ActionResult:
        """Press a key combination (e.g., 'ctrl', 'c')."""
        if not keys or not all(isinstance(k, str) and k.strip() for k in keys) or len(keys) > 6:
            return ActionResult.fail(message="hotkey needs 1-6 non-empty key names", intent="hotkey")
        denied = self._gate("desktop.hotkey_exec" if self._combo_executes(keys) else "desktop.hotkey", "hotkey")
        if denied is not None:
            return denied

        try:
            pag = self._get_pyautogui()
            pag.hotkey(*keys)
            combo = "+".join(keys)
            self.logger.info(f"[DESKTOP] Hotkey: {combo}")
            return ActionResult.ok(message=f"Hotkey: {combo}", intent="hotkey")
        except Exception as e:
            logging.debug("[core/desktop_control.py] hotkey: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="hotkey")

    def key_down(self, key: str) -> ActionResult:
        """Hold down a key."""
        if not isinstance(key, str) or not key.strip():
            return ActionResult.fail(message="key must be a non-empty string", intent="key_down")
        nk = _norm_key(key)
        risky = self._combo_executes([key]) or nk in ("alt", "ctrl")  # modifiers can arm a later combo
        denied = self._gate("desktop.key_down_exec" if risky else "desktop.key_down", "key_down")
        if denied is not None:
            return denied
        try:
            pag = self._get_pyautogui()
            pag.keyDown(key)
            self._held_keys.add(nk)
            return ActionResult.ok(message=f"Key down: {key}", intent="key_down")
        except Exception as e:
            logging.debug("[core/desktop_control.py] key_down: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="key_down")

    def key_up(self, key: str) -> ActionResult:
        """Release a key."""
        if not isinstance(key, str) or not key.strip():
            return ActionResult.fail(message="key must be a non-empty string", intent="key_up")
        denied = self._gate("desktop.key_up", "key_up")
        if denied is not None:
            return denied
        try:
            pag = self._get_pyautogui()
            pag.keyUp(key)
            self._held_keys.discard(_norm_key(key))
            return ActionResult.ok(message=f"Key up: {key}", intent="key_up")
        except Exception as e:
            logging.debug("[core/desktop_control.py] key_up: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="key_up")

    # --- CLIPBOARD OPERATIONS ---

    def clipboard_copy(self, text: str) -> ActionResult:
        """Copy text to clipboard."""
        denied = self._gate("desktop.clipboard_copy", "clipboard_copy")
        if denied is not None:
            return denied

        try:
            if not isinstance(text, str) or len(text) > 1_000_000:
                raise ValueError("text must be a string of at most 1,000,000 chars")
            clip = self._get_pyperclip()
            clip.copy(text)
            self.logger.info(f"[DESKTOP] Clipboard copy: {len(text)} chars")
            return ActionResult.ok(message=f"Copied {len(text)} chars", intent="clipboard_copy")
        except Exception as e:
            logging.debug("[core/desktop_control.py] clipboard_copy: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="clipboard_copy")

    def clipboard_paste(self) -> ActionResult:
        """Read text from the clipboard (it may hold anything, so it counts as untrusted content)."""
        denied = self._gate("desktop.clipboard_paste", "clipboard_paste")
        if denied is not None:
            return denied
        try:
            clip = self._get_pyperclip()
            text = clip.paste()
            self.logger.info(f"[DESKTOP] Clipboard paste: {len(text)} chars")
            mark = getattr(self.permissions, "mark_untrusted", None)
            if mark:
                mark("desktop.clipboard_paste")
            return ActionResult.ok(message=text, intent="clipboard_paste", data={"text": text})
        except Exception as e:
            logging.debug("[core/desktop_control.py] clipboard_paste: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="clipboard_paste")

    def clipboard_clear(self) -> ActionResult:
        """Clear the clipboard."""
        denied = self._gate("desktop.clipboard_clear", "clipboard_clear")
        if denied is not None:
            return denied
        try:
            clip = self._get_pyperclip()
            clip.copy("")
            return ActionResult.ok(message="Clipboard cleared", intent="clipboard_clear")
        except Exception as e:
            logging.debug("[core/desktop_control.py] clipboard_clear: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="clipboard_clear")

    # --- WINDOW OPERATIONS ---

    def get_active_window(self) -> ActionResult:
        """Get the title of the active window."""
        denied = self._gate("desktop.active_window", "active_window")
        if denied is not None:
            return denied
        try:
            import pygetwindow as gw
            win = gw.getActiveWindow()
            if win:
                return ActionResult.ok(
                    message=win.title,
                    intent="active_window",
                    data={"title": win.title, "x": win.left, "y": win.top,
                          "width": win.width, "height": win.height}
                )
            return ActionResult.ok(message="No active window", intent="active_window")
        except Exception as e:
            logging.debug("[core/desktop_control.py] active_window: %s: %s", type(e).__name__, e)
            # Fallback to system engine
            try:
                from engines.system import SystemCtrl
                title = SystemCtrl.get_active_window_title()
                return ActionResult.ok(message=title, intent="active_window")
            except Exception as _e:
                logging.debug("[core/desktop_control.py] active_window fallback: %s: %s", type(_e).__name__, _e)
                return ActionResult.fail(message=str(e), intent="active_window")

    def list_windows(self) -> ActionResult:
        """List all visible windows."""
        denied = self._gate("desktop.list_windows", "list_windows")
        if denied is not None:
            return denied
        try:
            import pygetwindow as gw
            windows = gw.getAllWindows()
            visible = [w.title for w in windows if w.visible and w.title]
            return ActionResult.ok(
                message=f"{len(visible)} windows",
                intent="list_windows",
                data={"windows": visible}
            )
        except Exception as e:
            logging.debug("[core/desktop_control.py] list_windows: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="list_windows")

    def focus_window(self, title: str) -> ActionResult:
        """Bring a window to focus by title (partial match)."""
        denied = self._gate("desktop.focus", "focus_window")
        if denied is not None:
            return denied

        try:
            if not isinstance(title, str) or not title.strip() or len(title) > 200:
                raise ValueError("title must be a non-empty string of at most 200 chars")
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title)
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                self.logger.info(f"[DESKTOP] Focused window: {win.title}")
                return ActionResult.ok(message=f"Focused: {win.title}", intent="focus_window")
            return ActionResult.fail(message=f"No window matching '{title}'", intent="focus_window")
        except Exception as e:
            logging.debug("[core/desktop_control.py] focus_window: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="focus_window")

    def close_window(self, title: str) -> ActionResult:
        """Close a window by title."""
        denied = self._gate("desktop.close_window", "close_window")
        if denied is not None:
            return denied

        try:
            if not isinstance(title, str) or not title.strip() or len(title) > 200:
                raise ValueError("title must be a non-empty string of at most 200 chars")
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].close()
                self.logger.info(f"[DESKTOP] Closed window: {title}")
                return ActionResult.ok(message=f"Closed: {title}", intent="close_window")
            return ActionResult.fail(message=f"No window matching '{title}'", intent="close_window")
        except Exception as e:
            logging.debug("[core/desktop_control.py] close_window: %s: %s", type(e).__name__, e)
            return ActionResult.fail(message=str(e), intent="close_window")

    # --- UTILITY ---

    def wait(self, seconds: float) -> ActionResult:
        """Wait for a specified duration (bounded to 0..30 s)."""
        denied = self._gate("desktop.wait", "wait")
        if denied is not None:
            return denied
        try:
            seconds = float(self._num(seconds, "seconds"))
        except ValueError as e:
            return ActionResult.fail(message=str(e), intent="wait")
        seconds = min(max(seconds, 0.0), MAX_WAIT_SECONDS)
        time.sleep(seconds)
        return ActionResult.ok(message=f"Waited {seconds}s", intent="wait")

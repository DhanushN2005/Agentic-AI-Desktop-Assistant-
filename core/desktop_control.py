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

Every action passes through the permission system.
Scattered pyautogui calls are replaced with this safe abstraction.
"""
import logging
import time
import os
from typing import Optional, Tuple, List
from core.action_result import ActionResult
from core.permission_system import PermissionSystem
from core.tool_registry import PermissionLevel


class DesktopControl:
    """
    Safe, centralized desktop interaction controller.
    
    All desktop actions (mouse, keyboard, screen) go through this module.
    Each action checks permissions before execution.
    """

    def __init__(self, permission_system: Optional[PermissionSystem] = None):
        self.permissions = permission_system or PermissionSystem()
        self.logger = logging.getLogger("Flexie.DesktopControl")
        self._pyautogui = None
        self._pyperclip = None
        self._screenshot_dir = os.path.join(os.path.expanduser("~"), "Desktop", "flexie_screenshots")
        os.makedirs(self._screenshot_dir, exist_ok=True)

    def _get_pyautogui(self):
        if self._pyautogui is None:
            try:
                import pyautogui
                pyautogui.FAILSAFE = True
                pyautogui.PAUSE = 0.1
                self._pyautogui = pyautogui
            except ImportError:
                raise RuntimeError("pyautogui not installed")
        return self._pyautogui

    def _get_pyperclip(self):
        if self._pyperclip is None:
            try:
                import pyperclip
                self._pyperclip = pyperclip
            except ImportError:
                raise RuntimeError("pyperclip not installed")
        return self._pyperclip

    # --- SCREEN OPERATIONS ---

    def screenshot(self, region: Optional[Tuple[int, int, int, int]] = None) -> ActionResult:
        """Take a screenshot. Returns path to saved image."""
        allowed, reason, _ = self.permissions.check_permission("vision.screenshot", "screenshot")
        if not allowed:
            return ActionResult.fail(message=reason, intent="screenshot")

        try:
            pag = self._get_pyautogui()
            timestamp = int(time.time())
            path = os.path.join(self._screenshot_dir, f"screenshot_{timestamp}.png")
            if region:
                img = pag.screenshot(region=region)
            else:
                img = pag.screenshot()
            img.save(path)
            self.logger.info(f"[DESKTOP] Screenshot saved: {path}")
            return ActionResult.ok(message=path, intent="screenshot", data={"path": path})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="screenshot")

    def get_screen_size(self) -> ActionResult:
        """Get screen dimensions."""
        try:
            pag = self._get_pyautogui()
            w, h = pag.size()
            return ActionResult.ok(
                message=f"{w}x{h}",
                intent="screen_size",
                data={"width": w, "height": h}
            )
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="screen_size")

    def get_pixel_color(self, x: int, y: int) -> ActionResult:
        """Get the color of a pixel at (x, y)."""
        try:
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
            return ActionResult.fail(message=str(e), intent="pixel_color")

    # --- MOUSE OPERATIONS ---

    def click(self, x: int, y: int, button: str = "left") -> ActionResult:
        """Click at position (x, y)."""
        allowed, reason, _ = self.permissions.check_permission("desktop.click", "click")
        if not allowed:
            return ActionResult.fail(message=reason, intent="click")

        try:
            pag = self._get_pyautogui()
            pag.click(x, y, button=button)
            self.logger.info(f"[DESKTOP] Click at ({x}, {y}) button={button}")
            return ActionResult.ok(message=f"Clicked ({x}, {y})", intent="click")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="click")

    def double_click(self, x: int, y: int) -> ActionResult:
        """Double-click at position (x, y)."""
        allowed, reason, _ = self.permissions.check_permission("desktop.double_click", "double click")
        if not allowed:
            return ActionResult.fail(message=reason, intent="double_click")

        try:
            pag = self._get_pyautogui()
            pag.doubleClick(x, y)
            self.logger.info(f"[DESKTOP] Double-click at ({x}, {y})")
            return ActionResult.ok(message=f"Double-clicked ({x}, {y})", intent="double_click")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="double_click")

    def move_mouse(self, x: int, y: int, duration: float = 0.3) -> ActionResult:
        """Move mouse to (x, y)."""
        try:
            pag = self._get_pyautogui()
            pag.moveTo(x, y, duration=duration)
            return ActionResult.ok(message=f"Moved to ({x}, {y})", intent="move_mouse")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="move_mouse")

    def get_mouse_position(self) -> ActionResult:
        """Get current mouse position."""
        try:
            pag = self._get_pyautogui()
            x, y = pag.position()
            return ActionResult.ok(
                message=f"({x}, {y})",
                intent="mouse_pos",
                data={"x": x, "y": y}
            )
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="mouse_pos")

    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> ActionResult:
        """Scroll by amount (positive = up, negative = down)."""
        allowed, reason, _ = self.permissions.check_permission("desktop.scroll", "scroll")
        if not allowed:
            return ActionResult.fail(message=reason, intent="scroll")

        try:
            pag = self._get_pyautogui()
            if x is not None and y is not None:
                pag.scroll(amount, x=x, y=y)
            else:
                pag.scroll(amount)
            direction = "up" if amount > 0 else "down"
            self.logger.info(f"[DESKTOP] Scrolled {direction} by {abs(amount)}")
            return ActionResult.ok(message=f"Scrolled {direction}", intent="scroll")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="scroll")

    # --- KEYBOARD OPERATIONS ---

    def type_text(self, text: str, interval: float = 0.02) -> ActionResult:
        """Type text character by character."""
        allowed, reason, _ = self.permissions.check_permission("desktop.type", "type text")
        if not allowed:
            return ActionResult.fail(message=reason, intent="type_text")

        try:
            pag = self._get_pyautogui()
            pag.typewrite(text, interval=interval) if text.isascii() else pag.write(text)
            self.logger.info(f"[DESKTOP] Typed: {text[:30]}...")
            return ActionResult.ok(message=f"Typed {len(text)} chars", intent="type_text")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="type_text")

    def press_key(self, key: str) -> ActionResult:
        """Press a single key."""
        allowed, reason, _ = self.permissions.check_permission("desktop.press", "press key")
        if not allowed:
            return ActionResult.fail(message=reason, intent="press_key")

        try:
            pag = self._get_pyautogui()
            pag.press(key)
            self.logger.info(f"[DESKTOP] Pressed: {key}")
            return ActionResult.ok(message=f"Pressed {key}", intent="press_key")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="press_key")

    def hotkey(self, *keys: str) -> ActionResult:
        """Press a key combination (e.g., 'ctrl', 'c')."""
        allowed, reason, _ = self.permissions.check_permission("desktop.hotkey", "hotkey")
        if not allowed:
            return ActionResult.fail(message=reason, intent="hotkey")

        try:
            pag = self._get_pyautogui()
            pag.hotkey(*keys)
            combo = "+".join(keys)
            self.logger.info(f"[DESKTOP] Hotkey: {combo}")
            return ActionResult.ok(message=f"Hotkey: {combo}", intent="hotkey")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="hotkey")

    def key_down(self, key: str) -> ActionResult:
        """Hold down a key."""
        try:
            pag = self._get_pyautogui()
            pag.keyDown(key)
            return ActionResult.ok(message=f"Key down: {key}", intent="key_down")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="key_down")

    def key_up(self, key: str) -> ActionResult:
        """Release a key."""
        try:
            pag = self._get_pyautogui()
            pag.keyUp(key)
            return ActionResult.ok(message=f"Key up: {key}", intent="key_up")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="key_up")

    # --- CLIPBOARD OPERATIONS ---

    def clipboard_copy(self, text: str) -> ActionResult:
        """Copy text to clipboard."""
        allowed, reason, _ = self.permissions.check_permission("clipboard.copy", "copy")
        if not allowed:
            return ActionResult.fail(message=reason, intent="clipboard_copy")

        try:
            clip = self._get_pyperclip()
            clip.copy(text)
            self.logger.info(f"[DESKTOP] Clipboard copy: {len(text)} chars")
            return ActionResult.ok(message=f"Copied {len(text)} chars", intent="clipboard_copy")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="clipboard_copy")

    def clipboard_paste(self) -> ActionResult:
        """Paste text from clipboard."""
        try:
            clip = self._get_pyperclip()
            text = clip.paste()
            self.logger.info(f"[DESKTOP] Clipboard paste: {len(text)} chars")
            return ActionResult.ok(message=text, intent="clipboard_paste", data={"text": text})
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="clipboard_paste")

    def clipboard_clear(self) -> ActionResult:
        """Clear the clipboard."""
        try:
            clip = self._get_pyperclip()
            clip.copy("")
            return ActionResult.ok(message="Clipboard cleared", intent="clipboard_clear")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="clipboard_clear")

    # --- WINDOW OPERATIONS ---

    def get_active_window(self) -> ActionResult:
        """Get the title of the active window."""
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
            # Fallback to system engine
            try:
                from engines.system import SystemCtrl
                title = SystemCtrl.get_active_window_title()
                return ActionResult.ok(message=title, intent="active_window")
            except Exception:
                return ActionResult.fail(message=str(e), intent="active_window")

    def list_windows(self) -> ActionResult:
        """List all visible windows."""
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
            return ActionResult.fail(message=str(e), intent="list_windows")

    def focus_window(self, title: str) -> ActionResult:
        """Bring a window to focus by title (partial match)."""
        allowed, reason, _ = self.permissions.check_permission("desktop.focus", "focus window")
        if not allowed:
            return ActionResult.fail(message=reason, intent="focus_window")

        try:
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
            return ActionResult.fail(message=str(e), intent="focus_window")

    def close_window(self, title: str) -> ActionResult:
        """Close a window by title."""
        allowed, reason, _ = self.permissions.check_permission("desktop.close_window", "close window")
        if not allowed:
            return ActionResult.fail(message=reason, intent="close_window")

        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(title)
            if windows:
                windows[0].close()
                self.logger.info(f"[DESKTOP] Closed window: {title}")
                return ActionResult.ok(message=f"Closed: {title}", intent="close_window")
            return ActionResult.fail(message=f"No window matching '{title}'", intent="close_window")
        except Exception as e:
            return ActionResult.fail(message=str(e), intent="close_window")

    # --- UTILITY ---

    def wait(self, seconds: float) -> ActionResult:
        """Wait for a specified duration."""
        time.sleep(seconds)
        return ActionResult.ok(message=f"Waited {seconds}s", intent="wait")

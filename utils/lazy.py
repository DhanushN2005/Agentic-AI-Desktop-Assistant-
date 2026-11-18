"""Import heavy optional libraries on first use instead of at program start.

``pyautogui``, ``pygame``, ``pytesseract`` and ``playwright`` together cost several
seconds of import time but are only needed when a matching command is actually run.
"""
import importlib
import importlib.util
import threading


class LazyModule:
    """Stand-in for a module that is imported on first attribute access.

    ``bool(lazy)`` is False when the library is not installed (or fails to import),
    so ``if not pyautogui:`` replaces the old ``pyautogui is None`` check.
    """

    def __init__(self, name: str, attr: str | None = None):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_attr", attr)
        object.__setattr__(self, "_mod", None)
        object.__setattr__(self, "_failed", False)
        object.__setattr__(self, "_lock", threading.Lock())

    def _load(self):
        mod = object.__getattribute__(self, "_mod")
        if mod is not None:
            return mod
        with object.__getattribute__(self, "_lock"):
            mod = object.__getattribute__(self, "_mod")
            if mod is None:
                mod = importlib.import_module(object.__getattribute__(self, "_name"))
                attr = object.__getattribute__(self, "_attr")
                if attr:
                    mod = getattr(mod, attr)
                object.__setattr__(self, "_mod", mod)
        return mod

    def available(self) -> bool:
        """Cheap check that does not import: is the package installed at all?"""
        try:
            return importlib.util.find_spec(object.__getattribute__(self, "_name").split(".")[0]) is not None
        except (ImportError, ValueError):
            return False

    def __getattr__(self, item):
        return getattr(self._load(), item)

    def __call__(self, *a, **k):
        return self._load()(*a, **k)

    def __bool__(self):
        if object.__getattribute__(self, "_failed"):
            return False
        try:
            self._load()
            return True
        except Exception:
            object.__setattr__(self, "_failed", True)
            return False

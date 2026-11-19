"""Vision mode: the 3D hand-gesture orb, now a panel of the web dashboard.

The orb is built from ``interface/orb`` into ``interface/static/`` (committed), and the dashboard served
by the web bridge at http://localhost:8766/ shows it as an overlay (tab "Orb", or the ``#orb`` address).
It is the same page, origin and WebSocket token as the dashboard, so it shows live assistant state.
There is nothing to install or start besides the bridge.
"""
from __future__ import annotations

import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(_PROJECT_ROOT, "interface", "static")
DASHBOARD_URL = "http://localhost:8766/"
ORB_URL = DASHBOARD_URL + "#orb"
_REQUIRED_FILES = ("orb.js", "orb.css", "orb-panel.js")


class VisionMode:
    """Facts about the orb panel; the handler does the opening (it owns the bridge start)."""

    def __init__(self, static_dir: str | None = None):
        self.static_dir = static_dir or STATIC_DIR

    @property
    def url(self) -> str:
        return ORB_URL

    def missing_files(self) -> list[str]:
        return [f for f in _REQUIRED_FILES if not os.path.isfile(os.path.join(self.static_dir, f))]

    def problem(self) -> str | None:
        """Why vision mode cannot open (None = it can)."""
        missing = self.missing_files()
        if missing:
            return ("The orb files are missing (" + ", ".join(missing) + "). "
                    "Rebuild them with 'npm install && npm run build' in interface/orb.")
        return None

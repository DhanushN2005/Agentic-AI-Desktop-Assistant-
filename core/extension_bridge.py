"""Flexie -> browser-extension channel (the extension polls; Flexie queues tasks).

The extension can already call Flexie (HTTP). The reverse - Flexie asking the extension to read your
current tab or act on a page - needs a queue the extension drains:

    Flexie handler --request()--> [queue] <--GET /api/flexie/extension/poll-- extension service worker
    Flexie handler <--result----- [done]  <--POST /api/flexie/extension/result-- extension

Everything is in memory, bounded and time-limited. Only the task kinds in ``KINDS`` exist, payloads are
validated and size-capped, and a task that nobody picks up expires. This module knows nothing about HTTP.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any

# kind -> (what it does, effect). "read" kinds only look at the page; "act" kinds change something in the
# user's real browser and are gated by the permission system before a handler may queue them.
KINDS: dict[str, tuple[str, str]] = {
    "active_tab": ("title and address of the tab you are looking at", "read"),
    "list_tabs": ("titles and addresses of your open tabs", "read"),
    "read_page": ("text of the tab you are looking at", "read"),
    "extract_tables": ("tables on the page", "read"),
    "extract_links": ("links on the page", "read"),
    "find_text": ("find and highlight text on the page", "read"),
    "scroll": ("scroll the page", "read"),
    "click": ("click an element", "act"),
    "fill": ("type into a field", "act"),
    "key": ("press a key", "act"),
    "navigate": ("open an address in the current tab", "act"),
    "submit": ("submit a form", "act"),
}
ACT_KINDS = frozenset(k for k, (_d, effect) in KINDS.items() if effect == "act")

MAX_PENDING = 20
MAX_STRING = 2000                # any single payload string
MAX_RESULT_CHARS = 200_000       # the result is trimmed, never refused
TASK_TTL = 30.0                  # an unclaimed task older than this is dropped
CONNECTED_WITHIN = 45.0          # "connected" = polled this recently
MAX_POLL_WAIT = 25.0

_ALLOWED_PAYLOAD_KEYS = {"target", "selector", "label", "value", "key", "url", "text", "direction", "top"}


class ExtensionBridgeError(Exception):
    """A task could not be queued or did not finish (bad kind, extension not connected, timeout...)."""


def validate_task(kind: str, payload: dict | None) -> dict:
    """Return a clean payload for ``kind`` or raise ExtensionBridgeError."""
    if kind not in KINDS:
        raise ExtensionBridgeError(f"unknown task kind {kind!r}")
    payload = dict(payload or {})
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in _ALLOWED_PAYLOAD_KEYS:
            raise ExtensionBridgeError(f"unexpected field {key!r}")
        if key == "top":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ExtensionBridgeError("top must be a number")
            clean[key] = int(value)
        else:
            if not isinstance(value, str) or len(value) > MAX_STRING:
                raise ExtensionBridgeError(f"{key} must be text of at most {MAX_STRING} characters")
            clean[key] = value
    if kind == "navigate":
        url = clean.get("url", "")
        if not url.lower().startswith(("http://", "https://")):
            raise ExtensionBridgeError("navigate only opens http or https addresses")
    if kind == "click" and not clean.get("target"):
        raise ExtensionBridgeError("click needs a target")
    if kind == "fill" and not (clean.get("selector") or clean.get("label")):
        raise ExtensionBridgeError("fill needs a selector or a label")
    if kind == "fill" and "value" not in clean:
        raise ExtensionBridgeError("fill needs a value")
    if kind == "find_text" and not clean.get("text"):
        raise ExtensionBridgeError("find_text needs text")
    if kind == "key" and not clean.get("key"):
        raise ExtensionBridgeError("key needs a key")
    return clean


class _Task:
    __slots__ = ("id", "kind", "payload", "created", "done", "result")

    def __init__(self, task_id: str, kind: str, payload: dict):
        self.id, self.kind, self.payload = task_id, kind, payload
        self.created = time.monotonic()
        self.done = threading.Event()
        self.result: dict | None = None


class ExtensionBridge:
    """Thread-safe queue between Flexie's handlers and the polling extension."""

    def __init__(self):
        self._cond = threading.Condition()
        self._pending: deque[_Task] = deque()
        self._inflight: dict[str, _Task] = {}
        self._ids = itertools.count(1)
        self.last_poll = 0.0

    # ---- Flexie side -------------------------------------------------------
    def connected(self) -> bool:
        return self.last_poll > 0 and time.monotonic() - self.last_poll < CONNECTED_WITHIN

    def request(self, kind: str, payload: dict | None = None, timeout: float = 20.0) -> dict:
        """Queue a task and wait for the extension's answer: ``{"ok": bool, "data": ..., "error": ...}``.

        Raises ExtensionBridgeError if the extension is not connected, the queue is full, the task is
        invalid, or no answer arrives within ``timeout`` seconds.
        """
        clean = validate_task(kind, payload)
        if not self.connected():
            raise ExtensionBridgeError("the Flexie browser extension is not connected")
        with self._cond:
            self._expire_locked()
            if len(self._pending) >= MAX_PENDING:
                raise ExtensionBridgeError("too many pending browser tasks")
            task = _Task(f"t{next(self._ids)}", kind, clean)
            self._pending.append(task)
            self._cond.notify_all()
        if not task.done.wait(timeout):
            with self._cond:
                try:
                    self._pending.remove(task)
                except ValueError:
                    pass
                self._inflight.pop(task.id, None)
            raise ExtensionBridgeError("the browser did not answer in time")
        return task.result or {"ok": False, "error": "empty result"}

    # ---- extension side (called from the API) -------------------------------
    def poll(self, wait: float = 20.0) -> dict | None:
        """Hand the extension its next task, waiting up to ``wait`` seconds. Marks the extension as connected."""
        wait = max(0.0, min(float(wait), MAX_POLL_WAIT))
        deadline = time.monotonic() + wait
        with self._cond:
            self.last_poll = time.monotonic()
            while True:
                self._expire_locked()
                if self._pending:
                    task = self._pending.popleft()
                    self._inflight[task.id] = task
                    return {"id": task.id, "kind": task.kind, "payload": task.payload, "age": round(time.monotonic() - task.created, 2)}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.last_poll = time.monotonic()
                    return None
                self._cond.wait(remaining)
                self.last_poll = time.monotonic()

    def complete(self, task_id: str, ok: bool, data: Any = None, error: str | None = None) -> bool:
        """Record the extension's answer. False if the task is unknown (already finished or expired)."""
        with self._cond:
            task = self._inflight.pop(str(task_id), None)
        if task is None:
            return False
        task.result = {"ok": bool(ok), "data": _trim(data), "error": (str(error)[:500] if error else None)}
        task.done.set()
        return True

    # ---- internals -----------------------------------------------------------
    def _expire_locked(self) -> None:
        now = time.monotonic()
        while self._pending and now - self._pending[0].created > TASK_TTL:
            stale = self._pending.popleft()
            stale.result = {"ok": False, "data": None, "error": "expired before the browser picked it up"}
            stale.done.set()

    def status(self) -> dict:
        with self._cond:
            return {"connected": self.connected(), "pending": len(self._pending), "in_flight": len(self._inflight)}


def _trim(data: Any, limit: int = MAX_RESULT_CHARS) -> Any:
    """Cap a result so a huge page can never blow up memory; strings and nested text are cut."""
    if isinstance(data, str):
        return data[:limit]
    if isinstance(data, list):
        return [_trim(x, limit // 4 or 1) for x in data[:500]]
    if isinstance(data, dict):
        return {str(k)[:100]: _trim(v, limit // 4 or 1) for k, v in list(data.items())[:100]}
    return data


_bridge: ExtensionBridge | None = None
_bridge_lock = threading.Lock()


def get_bridge() -> ExtensionBridge:
    """The one shared bridge (the API server and the orchestrator's handlers use the same instance)."""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = ExtensionBridge()
        return _bridge

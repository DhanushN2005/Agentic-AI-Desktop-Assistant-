"""UDP control-plane auth — shared by orchestrator, PyQt UI and web bridge.

Protocol: every datagram sent TO the orchestrator must look like::

    TOKEN:<token> <original payload>

``get_token()`` resolves the per-run token in this order:

1. ``FLEXIE_UDP_TOKEN`` environment variable — set by ``main.py`` at startup and
   inherited by every child process it spawns (PyQt UI, web bridge).
2. The per-run token file ``.flexie_udp_token`` (written by ``main.py`` via
   ``publish_token()``). This is what makes a *standalone* process such as
   ``python interface/web_ui_bridge.py`` — started by hand instead of by
   ``main.py`` — authenticate successfully instead of silently generating its
   own private token and having every command rejected.
3. Generate a new token and persist it, so two hand-started processes agree.

``pack()`` prefixes, ``unpack()`` verifies with ``hmac.compare_digest`` and
returns the payload, or ``None`` when auth fails (caller must reject).
"""
import hmac
import json
import logging
import os
import secrets
import threading

ENV_VAR = "FLEXIE_UDP_TOKEN"
_PREFIX = "TOKEN:"

# Per-run token file, project root (…/flexie_v2/.flexie_udp_token).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(_PROJECT_ROOT, ".flexie_udp_token")


def _read_token_file() -> str:
    """Return the persisted token, or "" when the file is missing/unreadable.

    Read on every call (never cached) so an already-running client picks up a
    freshly rotated token on its next send instead of being rejected forever.
    Only reached when FLEXIE_UDP_TOKEN is unset, i.e. never in the hot path of a
    normally started orchestrator.
    """
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def publish_token(token: str) -> bool:
    """Persist ``token`` to the per-run token file (best effort).

    Called by ``main.py`` on every start. Returns True on success.
    """
    if not token:
        return False
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(token)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError as e:
            # Windows: chmod only toggles the read-only bit; the file lives in
            # the user's own project folder, so this is not fatal.
            logging.debug("[utils/udp_auth.py:publish_token] chmod skipped: %s: %s", type(e).__name__, e)
        return True
    except OSError as e:
        logging.debug("[utils/udp_auth.py:publish_token] %s: %s", type(e).__name__, e)
        return False


def get_token(prefer_file: bool = False) -> str:
    """Resolve the per-run token.

    ``prefer_file=True`` reads the published token file BEFORE the environment,
    so a long-lived child (the web bridge) that inherited a stale env value from
    a previous main.py run follows a rotated token instead of being rejected.
    """
    if prefer_file:
        tok = _read_token_file()
        if tok:
            return tok
    tok = os.getenv(ENV_VAR, "")
    if tok:
        return tok
    tok = _read_token_file()
    if tok:
        return tok
    tok = secrets.token_urlsafe(24)
    publish_token(tok)
    return tok


def pack(message: str, prefer_file: bool = False) -> str:
    return f"{_PREFIX}{get_token(prefer_file)} {message}"


def unpack(raw: str):
    """Return payload if ``raw`` carries a valid token, else None."""
    if not raw or not raw.startswith(_PREFIX):
        return None
    rest = raw[len(_PREFIX):]
    head, sep, payload = rest.partition(" ")
    if not sep or not head:
        return None
    try:
        expected = get_token()
    except Exception:
        return None
    if not hmac.compare_digest(head, expected):
        return None
    return payload


# ── UI-bound datagrams (orchestrator/voice -> Qt UI / web bridge) ───────────
ALLOW_UNSIGNED_ENV = "FLEXIE_ALLOW_UNSIGNED_UI"
DEFAULT_UI_PORT = 9886   # Qt desktop UI (historic port, so old senders still reach it)
WEB_UI_PORT = 9888       # web bridge gets its own port (no more shared 9886)
UI_PORTS_FILE = os.path.join(_PROJECT_ROOT, ".flexie_ui_ports")
_ports_lock = threading.Lock()


def decode_ui_datagram(data) -> str | None:
    """Verify + decode one UI-bound datagram.

    Signed (``TOKEN:<t> payload``) datagrams yield the payload. Unsigned ones are
    accepted only when ``FLEXIE_ALLOW_UNSIGNED_UI=1`` (migration aid). Bad bytes
    are decoded with ``errors='replace'``; never raises.
    """
    try:
        raw = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data)
        if raw.startswith(_PREFIX):
            return unpack(raw)
        if os.getenv(ALLOW_UNSIGNED_ENV, "") == "1":
            return raw
    except Exception as e:  # pragma: no cover - defensive
        logging.debug("[utils/udp_auth.py:decode_ui_datagram] %s: %s", type(e).__name__, e)
    return None


def _read_ports() -> list[int]:
    try:
        with open(UI_PORTS_FILE, encoding="utf-8") as fh:
            return [int(p) for p in json.load(fh) if 0 < int(p) < 65536]
    except (OSError, ValueError, TypeError):
        return []


def _write_ports(ports: list[int]) -> None:
    try:
        with open(UI_PORTS_FILE, "w", encoding="utf-8") as fh:
            json.dump(sorted(set(ports)), fh)
    except OSError as e:
        logging.debug("[utils/udp_auth.py:_write_ports] %s: %s", type(e).__name__, e)


def register_ui_port(port: int) -> None:
    """Announce that a UI process listens on ``port`` (subscriber registry)."""
    with _ports_lock:
        _write_ports(_read_ports() + [int(port)])


def unregister_ui_port(port: int) -> None:
    with _ports_lock:
        _write_ports([p for p in _read_ports() if p != int(port)])


def reset_ui_ports() -> None:
    """Called by main.py at startup: drop entries left by crashed processes."""
    with _ports_lock:
        _write_ports([])


def ui_ports() -> list[int]:
    """Ports a sender should fan UI updates out to (always includes the Qt port)."""
    ports = _read_ports()
    return sorted(set(ports) | {DEFAULT_UI_PORT})

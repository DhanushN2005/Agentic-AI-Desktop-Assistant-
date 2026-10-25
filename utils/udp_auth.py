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
import logging
import os
import secrets

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
        with open(TOKEN_FILE, "r", encoding="utf-8") as fh:
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


def get_token() -> str:
    tok = os.getenv(ENV_VAR, "")
    if tok:
        return tok
    tok = _read_token_file()
    if tok:
        return tok
    tok = secrets.token_urlsafe(24)
    publish_token(tok)
    return tok


def pack(message: str) -> str:
    return f"{_PREFIX}{get_token()} {message}"


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

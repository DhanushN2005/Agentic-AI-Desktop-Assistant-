"""UDP control-plane auth — shared by orchestrator, PyQt UI and web bridge.

Protocol: every datagram sent TO the orchestrator must look like::

    TOKEN:<token> <original payload>

``get_token()`` reads ``FLEXIE_UDP_TOKEN`` from the environment (set by
``main.py`` at startup) and generates + stores one if missing, so standalone
processes (bridge started by hand) still get a consistent in-process token.
``pack()`` prefixes, ``unpack()`` verifies with ``hmac.compare_digest`` and
returns the payload, or ``None`` when auth fails (caller must reject).
"""
import hmac
import os
import secrets

ENV_VAR = "FLEXIE_UDP_TOKEN"
_PREFIX = "TOKEN:"


def get_token() -> str:
    tok = os.getenv(ENV_VAR, "")
    if not tok:
        tok = secrets.token_urlsafe(24)
        os.environ[ENV_VAR] = tok
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

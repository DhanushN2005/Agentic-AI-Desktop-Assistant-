"""Light secret redaction for logs and persisted traces (best effort, regex based)."""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{12,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}=*"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|passwd)[\"']?\s*[=:]\s*[\"']?)[^\s\"',;&]{6,}"),
]


def redact_secrets(text) -> str:
    """Replace key-like substrings with ``[REDACTED]``. Never raises."""
    try:
        out = text if isinstance(text, str) else str(text)
        for pat in _PATTERNS:
            if pat.groups:
                out = pat.sub(lambda m: m.group(1) + "[REDACTED]", out)
            else:
                out = pat.sub("[REDACTED]", out)
        return out
    except Exception:
        return "[unprintable]"

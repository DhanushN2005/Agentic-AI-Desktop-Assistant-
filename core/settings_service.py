"""AI provider settings for the web dashboard (replaces the PyQt "API keys" dialog).

``snapshot()`` is what the dashboard may SEE: which providers have a key (masked hint only,
never the key itself), the chosen models and the active provider. ``apply()`` validates what
the dashboard sends back and writes it with ``Config.set_many_keys`` (which updates ``.env``
and ``os.environ``). Key values are never logged and never echoed back.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from utils.config import SUPPORTED_PROVIDERS, Config

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
_KEY_RE = re.compile(r"^[^\s\x00-\x1f\x7f\"'`$\\]{8,512}$")  # one token: no spaces, quotes or control chars
ACTIVE_CHOICES = ("auto",) + tuple(SUPPORTED_PROVIDERS) + ("ollama",)
MAX_URL = 300


def snapshot() -> dict:
    """Settings the dashboard may display (masked, never raw keys)."""
    masked = Config.get_all_keys_masked()
    providers = []
    for pid, meta in SUPPORTED_PROVIDERS.items():
        info = masked.get(pid, {})
        current = Config.get_model(pid) or meta.get("default_model", "")
        models = list(meta.get("models", []))
        if current and current not in models:
            models.insert(0, current)
        providers.append({
            "id": pid, "label": meta["label"], "env": meta["env"], "help": meta.get("help", ""),
            "placeholder": meta.get("placeholder", ""), "has_key": bool(info.get("has_key")),
            "hint": info.get("masked", ""), "model": current, "models": models,
        })
    return {
        "active": getattr(Config, "ACTIVE_PROVIDER", "auto") or "auto",
        "active_choices": list(ACTIVE_CHOICES),
        "providers": providers,
        "ollama": {"url": Config.OLLAMA_URL, "model": Config.OLLAMA_MODEL},
    }


def apply(payload: dict) -> tuple[int, list[str]]:
    """Validate ``payload`` and save it. Returns (number of settings written, problems).

    payload = {"keys": {provider: key}, "models": {provider: model}, "active": str,
               "ollama_url": str, "ollama_model": str}; every part is optional.
    Invalid entries are skipped and reported by name, never by value.
    """
    problems: list[str] = []
    updates: dict[str, str] = {}
    if not isinstance(payload, dict):
        return 0, ["settings payload must be an object"]

    keys = payload.get("keys") or {}
    if isinstance(keys, dict):
        for pid, value in keys.items():
            meta = SUPPORTED_PROVIDERS.get(str(pid).lower())
            if meta is None:
                problems.append(f"unknown provider: {str(pid)[:30]}")
            elif not isinstance(value, str) or not value.strip():
                continue  # empty = keep the saved key
            elif not _KEY_RE.match(value.strip()):
                problems.append(f"{pid}: key has an invalid format")
            else:
                updates[meta["env"]] = value.strip()

    models = payload.get("models") or {}
    if isinstance(models, dict):
        for pid, value in models.items():
            meta = SUPPORTED_PROVIDERS.get(str(pid).lower())
            if meta is None:
                problems.append(f"unknown provider: {str(pid)[:30]}")
            elif not isinstance(value, str) or not value.strip():
                continue
            elif not _MODEL_RE.match(value.strip()):
                problems.append(f"{pid}: model name has an invalid format")
            elif value.strip() != Config.get_model(str(pid).lower()):
                updates[meta["model_env"]] = value.strip()

    active = payload.get("active")
    if isinstance(active, str) and active.strip():
        active = "auto" if active.strip().lower().startswith("auto") else active.strip().lower()
        if active not in ACTIVE_CHOICES:
            problems.append("active provider is not one of the known providers")
        elif active != (getattr(Config, "ACTIVE_PROVIDER", "auto") or "auto"):
            updates["ACTIVE_PROVIDER"] = active

    url = payload.get("ollama_url")
    if isinstance(url, str) and url.strip():
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname or len(url) > MAX_URL or re.search(r"[\s\x00-\x1f\"'`$\\]", url):
            problems.append("ollama_url must be a plain http(s) address")
        elif url.strip() != Config.OLLAMA_URL:
            updates["OLLAMA_URL"] = url.strip()

    om = payload.get("ollama_model")
    if isinstance(om, str) and om.strip():
        if not _MODEL_RE.match(om.strip()):
            problems.append("ollama_model has an invalid format")
        elif om.strip() != Config.OLLAMA_MODEL:
            updates["OLLAMA_MODEL"] = om.strip()

    if not updates:
        return 0, problems
    if not Config.set_many_keys(updates):
        return 0, problems + ["could not write the .env file (check permissions)"]
    return len(updates), problems

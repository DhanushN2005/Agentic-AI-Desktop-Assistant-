"""AI provider settings for the web dashboard (replaces the PyQt "API keys" dialog).

``snapshot()`` is what the dashboard may SEE: which providers have a key (masked hint only,
never the key itself), the chosen models and the active provider. ``apply()`` validates what
the dashboard sends back and writes it with ``Config.set_many_keys`` (which updates ``.env``
and ``os.environ``). Key values are never logged and never echoed back.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from utils.config import SUPPORTED_PROVIDERS, Config

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
_KEY_RE = re.compile(r"^[^\s\x00-\x1f\x7f\"'`$\\]{8,512}$")  # one token: no spaces, quotes or control chars
ACTIVE_CHOICES = ("auto",) + tuple(SUPPORTED_PROVIDERS) + ("ollama",)
MAX_URL = 300

# Floating-orb styles the Qt HUD can wear (names match interface/orb_variants.py + orb_v2.py; a test keeps them in sync).
ORB_STYLES = ("classic", "hud", "plasma", "ring", "eye", "crystal", "sonar", "globe", "equalizer", "atom")

# Behaviour settings the dashboard may change. "live" ones are copied onto Config straight away, so they apply to the
# very next request - no restart. Others are saved and take effect on the next start (the dashboard says which).
BEHAVIOR = (
    {"env": "FLEXIE_CONVERSATION_HISTORY_TURNS", "attr": "CONVERSATION_HISTORY_TURNS", "type": "int", "min": 0, "max": 40,
     "group": "Conversation", "label": "Conversation memory", "unit": "turns", "live": True,
     "help": "How many earlier exchanges Flexie remembers when answering."},
    {"env": "FLEXIE_LLM_REQUEST_TIMEOUT", "attr": "LLM_REQUEST_TIMEOUT", "type": "float", "min": 3, "max": 60,
     "group": "Responses", "label": "AI request timeout", "unit": "seconds", "live": True,
     "help": "How long to wait for one AI provider before falling back to the next."},
    {"env": "FLEXIE_CODE_MAX_TOKENS", "attr": "CODE_MAX_TOKENS", "type": "int", "min": 256, "max": 16000,
     "group": "Responses", "label": "Code reply length", "unit": "tokens", "live": True,
     "help": "Upper limit for generated code in one reply."},
    {"env": "FLEXIE_VOICE_LISTEN_TIMEOUT", "attr": "VOICE_LISTEN_TIMEOUT", "type": "float", "min": 2, "max": 30,
     "group": "Voice", "label": "Listening window", "unit": "seconds", "live": True,
     "help": "How long Flexie waits for you to start speaking."},
    {"env": "FLEXIE_CHEAP_FIRST_ENABLED", "attr": "CHEAP_FIRST_ENABLED", "type": "bool",
     "group": "Routing", "label": "Cheap model first", "live": True,
     "help": "Try the cheapest capable model first and escalate only if needed."},
    {"env": "FLEXIE_LOCAL_FIRST", "attr": "LOCAL_FIRST", "type": "bool",
     "group": "Routing", "label": "Prefer local model", "live": True,
     "help": "Use the local (Ollama) model first when it is available."},
    {"env": "FLEXIE_LEARN_PREFERENCES", "attr": "LEARN_PREFERENCES", "type": "bool",
     "group": "Memory", "label": "Learn my preferences", "live": True,
     "help": "Remember lasting preferences you state (\"I prefer short answers\", \"call me Sam\"). See and delete them under Settings > Memory."},
    {"env": "FLEXIE_JOB_TOKEN_BUDGET", "attr": "JOB_TOKEN_BUDGET", "type": "int", "min": 5000, "max": 1000000,
     "group": "Builds", "label": "Build token budget", "unit": "tokens", "live": True,
     "help": "Most tokens one project build may use before it stops."},
    {"env": "FLEXIE_TTS_MODE", "attr": None, "type": "choice", "choices": ("neural", "sapi"),
     "group": "Voice", "label": "Voice engine", "live": False,
     "help": "neural = natural online voice, sapi = offline Windows voice. Applies after a restart."},
)
_BEHAVIOR_BY_ENV = {b["env"]: b for b in BEHAVIOR}


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
        "behavior": [{k: v for k, v in b.items() if k != "attr"} | {"value": _current(b)} for b in BEHAVIOR],
        "orb": {"style": orb_style(), "choices": list(ORB_STYLES)},
        "modes": list(Config.MODES),
    }


def orb_style() -> str:
    """The saved floating-orb style (``classic`` when unset or unknown)."""
    value = (os.environ.get("FLEXIE_ORB_STYLE", "") or "classic").strip().lower()
    return value if value in ORB_STYLES else "classic"


def _current(spec: dict):
    attr = spec.get("attr")
    if attr and hasattr(Config, attr):
        value = getattr(Config, attr)
    else:
        value = os.environ.get(spec["env"], "")
        if spec["type"] == "choice" and not value:
            value = spec["choices"][0]
    if spec["type"] == "bool":
        return bool(value)
    return value


def _clean_behavior(spec: dict, raw):
    """Validate one behaviour value against its spec. Returns (python value, env text) or raises ValueError."""
    kind = spec["type"]
    if kind == "bool":
        if isinstance(raw, str):
            raw = raw.strip().lower() in ("1", "true", "yes", "on")
        value = bool(raw)
        return value, "1" if value else "0"
    if kind == "choice":
        text = str(raw).strip().lower()
        if text not in spec["choices"]:
            raise ValueError("not one of " + ", ".join(spec["choices"]))
        return text, text
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError("must be a number")
    value = int(float(raw)) if kind == "int" else float(raw)
    if not (spec["min"] <= value <= spec["max"]):
        raise ValueError(f"must be between {spec['min']} and {spec['max']}")
    return value, str(value)


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

    live: dict[str, object] = {}
    behavior = payload.get("behavior") or {}
    if isinstance(behavior, dict):
        for env, raw in behavior.items():
            spec = _BEHAVIOR_BY_ENV.get(str(env))
            if spec is None:
                problems.append(f"unknown setting: {str(env)[:40]}")
                continue
            try:
                value, text = _clean_behavior(spec, raw)
            except (ValueError, OverflowError) as e:
                problems.append(f"{spec['label']}: {e}")
                continue
            if value != _current(spec):
                updates[spec["env"]] = text
                if spec.get("live") and spec.get("attr"):
                    live[spec["attr"]] = value

    style = payload.get("orb_style")
    if isinstance(style, str) and style.strip():
        style = style.strip().lower()
        if style not in ORB_STYLES:
            problems.append("orb style is not one of the known styles")
        elif style != orb_style():
            updates["FLEXIE_ORB_STYLE"] = style

    if not updates:
        return 0, problems
    if not Config.set_many_keys(updates):
        return 0, problems + ["could not write the .env file (check permissions)"]
    for attr, value in live.items():          # live apply: the next request already sees the new value
        setattr(Config, attr, value)
    return len(updates), problems

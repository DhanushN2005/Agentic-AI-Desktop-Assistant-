"""
LLM Provider Configuration — centralized, no hardcoded model names.

All LLM provider settings live here. Models are configurable through
environment variables or direct configuration. The system gracefully handles:
  - rate limits
  - timeouts
  - invalid API keys
  - provider outages
  - malformed responses
  - model unavailability

Providers are tried in priority order with automatic fallback. Every SDK client is built
with ``max_retries=0`` and an explicit timeout, so a failing provider costs at most one
timeout (the fallback to the next provider IS the retry). The circuit breaker is real:
three consecutive failures open the circuit for ``COOLDOWN_SECONDS``; after that one
half-open trial is allowed and a success closes it again.
"""
import copy
import importlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto

from core.telemetry.redact import redact_secrets
from core.telemetry.usage import messages_text, track_llm
from utils.config import Config


class ProviderStatus(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    UNAVAILABLE = auto()
    UNKNOWN = auto()


# --------------------------------------------------------------------- lazy Gemini SDK
def load_genai():
    """Import ``google.genai`` on first use (it costs ~6 s at import time). None if missing."""
    try:
        return importlib.import_module("google.genai")
    except Exception as e:  # ImportError or a broken install
        logging.debug("google.genai unavailable: %s: %s", type(e).__name__, e)
        return None


# Gemini rejects any request deadline under 10 s (HTTP 400); images need more headroom still.
GEMINI_MIN_TIMEOUT = 15.0


def build_gemini_client(api_key: str, timeout: float):
    """A google-genai client with an explicit request timeout (ms in the SDK), or None."""
    genai = load_genai()
    if genai is None:
        return None
    types = getattr(genai, "types", None)
    if types is not None and hasattr(types, "HttpOptions"):
        try:
            return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(max(timeout, GEMINI_MIN_TIMEOUT) * 1000)))
        except TypeError:
            pass  # very old SDK without http_options
    return genai.Client(api_key=api_key)


def gemini_generate(client, model: str, text: str, system: str | None = None, max_tokens: int | None = None,
                    temperature: float | None = None, img_path: str | None = None):
    """One Gemini call; the system prompt is ALWAYS passed as the system instruction."""
    config: dict = {}
    if system:
        config["system_instruction"] = system
    if max_tokens:
        config["max_output_tokens"] = max_tokens
    if temperature is not None:
        config["temperature"] = temperature
    kwargs = {"config": config} if config else {}
    if not img_path:
        return client.models.generate_content(model=model, contents=text, **kwargs)
    from PIL import Image  # lazy: only vision requests need it
    with Image.open(img_path) as img:
        img.load()
        # A full-resolution screenshot is slow to upload and costs more tokens for no gain:
        # 1280 px on the long side is plenty to read UI text.
        if max(img.size) > 1280:
            img = img.copy()
            img.thumbnail((1280, 1280))
        return client.models.generate_content(model=model, contents=[text, img], **kwargs)


def _default_model(name: str, fallback: str) -> str:
    return str(getattr(Config, f"{name.upper()}_MODEL", "") or fallback)


@dataclass
class LLMProvider:
    """Configuration for a single LLM provider."""
    name: str
    api_key_env: str  # Environment variable name for the API key
    model: str
    priority: int  # Lower = higher priority
    timeout: float = 30.0
    max_tokens: int = 2048
    temperature: float = 0.7
    supports_vision: bool = False
    supports_streaming: bool = False
    enabled: bool = True
    status: ProviderStatus = ProviderStatus.UNKNOWN
    last_error: str | None = None
    last_success: float | None = None
    consecutive_failures: int = 0
    max_consecutive_failures: int = 3
    cooldown_seconds: float = 300.0
    unavailable_since: float | None = None

    @property
    def api_key(self) -> str | None:
        """Get the API key from environment."""
        return os.environ.get(self.api_key_env)

    @property
    def circuit_open(self) -> bool:
        """True while the breaker is open (tripped and the cooldown has not elapsed)."""
        if self.status != ProviderStatus.UNAVAILABLE:
            return False
        if self.unavailable_since is None:
            return False
        return (time.time() - self.unavailable_since) < self.cooldown_seconds

    @property
    def is_available(self) -> bool:
        """Has a key, is enabled, and the circuit is closed or half-open (cooldown elapsed)."""
        return bool(self.enabled and self.api_key and not self.circuit_open)

    def record_success(self):
        """Record a successful call (closes the circuit)."""
        self.status = ProviderStatus.HEALTHY
        self.consecutive_failures = 0
        self.unavailable_since = None
        self.last_success = time.time()

    def record_failure(self, error: str):
        """Record a failed call. A failure of the half-open trial re-opens the circuit at once."""
        self.consecutive_failures += 1
        self.last_error = error
        if self.consecutive_failures >= self.max_consecutive_failures:
            self.status = ProviderStatus.UNAVAILABLE
            self.unavailable_since = time.time()
        else:
            self.status = ProviderStatus.DEGRADED

    def reset_status(self):
        """Reset provider status (e.g., after cooldown)."""
        self.status = ProviderStatus.UNKNOWN
        self.consecutive_failures = 0
        self.last_error = None
        self.unavailable_since = None


class LLMProviderManager:
    """
    Manages LLM providers with fallback, cooldown, and automatic recovery.

    Usage:
        manager = LLMProviderManager()
        result = manager.query("What is Python?")
        # Falls back through providers if one fails
    """

    # Default provider TEMPLATES — each manager gets its own copies (they carry mutable state).
    # Groq (fast+free) -> OpenAI -> DeepSeek -> Gemini -> Anthropic -> Mistral -> Ollama fallback handled in Brain
    DEFAULT_PROVIDERS = [
        LLMProvider(name="groq", api_key_env="GROQ_API_KEY", model="openai/gpt-oss-20b", priority=1, timeout=8.0, max_tokens=2048, supports_vision=False, supports_streaming=True),
        LLMProvider(name="openai", api_key_env="OPENAI_API_KEY", model="gpt-4o-mini", priority=2, timeout=8.0, max_tokens=2048, supports_vision=True, supports_streaming=True),
        LLMProvider(name="deepseek", api_key_env="DEEPSEEK_API_KEY", model="deepseek-chat", priority=3, timeout=8.0, max_tokens=2048, supports_vision=False, supports_streaming=True),
        LLMProvider(name="gemini", api_key_env="GEMINI_API_KEY", model="gemini-flash-latest", priority=4, timeout=15.0, max_tokens=2048, supports_vision=True, supports_streaming=True),
        LLMProvider(name="anthropic", api_key_env="ANTHROPIC_API_KEY", model="claude-sonnet-4-20250514", priority=5, timeout=8.0, max_tokens=2048, supports_vision=True, supports_streaming=False),
        LLMProvider(
            name="mistral",
            api_key_env="MISTRAL_API_KEY",
            model="mistral-small-latest",
            priority=6,
            timeout=10.0,
            max_tokens=2048,
            supports_vision=False,
            supports_streaming=True,
        ),
    ]

    # Cooldown period after the circuit opens (seconds)
    COOLDOWN_SECONDS = 300  # 5 minutes

    def __init__(self):
        self.providers: list[LLMProvider] = []
        self.logger = logging.getLogger("Flexie.LLMProviders")
        self._clients: dict[tuple, object] = {}
        self._clients_lock = threading.Lock()
        self._init_providers()
        self._load_config()

    def _init_providers(self):
        """Initialize provider copies — model from env, else Config, else the template default."""
        for template in self.DEFAULT_PROVIDERS:
            p = copy.copy(template)  # never share mutable state across managers
            p.cooldown_seconds = float(self.COOLDOWN_SECONDS)
            try:
                env_model = os.getenv(p.api_key_env.replace("_API_KEY", "_MODEL"), "")
                if not env_model:
                    try:
                        from utils.config import SUPPORTED_PROVIDERS as SP
                        me = SP.get(p.name, {}).get("model_env")
                        if me:
                            env_model = os.getenv(me, "")
                    except Exception as _e:
                        logging.debug("[core/llm_providers.py] SUPPORTED_PROVIDERS lookup failed: %s", _e)
                p.model = env_model.strip() if env_model else _default_model(p.name, p.model)
            except Exception as _e:
                logging.debug("[core/llm_providers.py] model init failed: %s: %s", type(_e).__name__, _e)
            self.providers.append(p)

    def _load_config(self):
        """Load provider overrides from config file if it exists."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "config", "llm_providers.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    data = json.load(f)
                for p_data in data.get("providers", []):
                    # Find existing provider or create new
                    existing = next((p for p in self.providers if p.name == p_data["name"]), None)
                    if existing:
                        for key, val in p_data.items():
                            if hasattr(existing, key):
                                setattr(existing, key, val)
                    else:
                        self.providers.append(LLMProvider(**p_data))
            except Exception as e:
                self.logger.warning("[LLM] Failed to load config: %s", redact_secrets(e))

    # ---------------------------------------------------------------- shared circuit breaker
    def _by_name(self, name: str) -> LLMProvider | None:
        return next((p for p in self.providers if p.name == name), None)

    def allow(self, name: str) -> bool:
        """May a caller (e.g. Brain's own direct clients) try this provider now? (circuit check only)"""
        p = self._by_name(name)
        return p is None or not p.circuit_open

    def report(self, name: str, ok: bool, error: str = "") -> None:
        """Feed an outcome observed outside the manager into the one shared circuit breaker."""
        p = self._by_name(name)
        if p is None:
            return
        if ok:
            p.record_success()
        else:
            p.record_failure(redact_secrets(error)[:200])

    def get_available_providers(self, vision_required: bool = False) -> list[LLMProvider]:
        """Get providers sorted by priority, filtered by availability + ACTIVE_PROVIDER."""
        active = os.getenv("ACTIVE_PROVIDER", "auto").lower()
        available = []
        for p in self.providers:
            if active != "auto" and p.name != active and p.name != "ollama":
                continue
            if not p.is_available:  # key present, enabled, circuit closed or half-open
                continue
            if vision_required and not p.supports_vision:
                continue
            # Refresh model from env on each call (hot-change)
            try:
                env_model = os.getenv(p.api_key_env.replace("_API_KEY", "_MODEL"), "")
                if env_model and env_model.strip() != p.model:
                    p.model = env_model.strip()
            except Exception as _e:
                logging.debug("[core/llm_providers.py] model refresh failed: %s: %s", type(_e).__name__, _e)
            available.append(p)
        return sorted(available, key=lambda x: x.priority)

    def set_provider_model(self, provider_name: str, model: str) -> bool:
        """Update model for a provider at runtime + persist to .env via Config."""
        provider_name = provider_name.lower()
        for p in self.providers:
            if p.name == provider_name:
                p.model = model.strip()
                try:
                    from utils.config import Config as C
                    C.set_model(provider_name, model.strip())
                except Exception as _e:
                    logging.debug("[core/llm_providers.py] set_model failed: %s: %s", type(_e).__name__, _e)
                return True
        return False

    def query(
        self,
        prompt: str,
        system_override: str | None = None,
        vision_required: bool = False,
        img_path: str | None = None,
        exclude=None,
        **kwargs,
    ) -> tuple[str, str]:
        """
        Query LLM providers with automatic fallback (one pass, no second round).

        ``exclude`` names providers the caller already tried this request (Brain passes the ones
        it called through its own clients) so nothing is asked twice.

        Returns:
            (response_text, provider_name)
        """
        skip = set(exclude or ())
        providers = [p for p in self.get_available_providers(vision_required) if p.name not in skip]
        if not providers:
            return "", "none"

        for provider in providers:
            try:
                response = self._call_provider(provider, prompt, system_override, img_path, **kwargs)
                if response and str(response).strip():
                    provider.record_success()
                    return response, provider.name
                provider.record_failure("empty response")
            except Exception as e:
                provider.record_failure(redact_secrets(e)[:200])
                self.logger.warning("[LLM] %s failed: %s", provider.name, redact_secrets(e))

        return "", "none"

    def _call_provider(
        self,
        provider: LLMProvider,
        prompt: str,
        system_override: str | None = None,
        img_path: str | None = None,
        **kwargs,
    ) -> str:
        """Call a specific LLM provider."""
        if provider.name == "groq":
            return self._call_groq(provider, prompt, system_override, **kwargs)
        elif provider.name == "openai":
            return self._call_openai_compatible(provider, prompt, system_override, base_url=None, **kwargs)
        elif provider.name == "deepseek":
            return self._call_openai_compatible(provider, prompt, system_override, base_url="https://api.deepseek.com", **kwargs)
        elif provider.name == "mistral":
            return self._call_openai_compatible(provider, prompt, system_override, base_url="https://api.mistral.ai/v1", **kwargs)
        elif provider.name == "together":
            return self._call_openai_compatible(provider, prompt, system_override, base_url="https://api.together.xyz/v1", **kwargs)
        elif provider.name == "gemini":
            return self._call_gemini(provider, prompt, system_override, img_path, **kwargs)
        elif provider.name == "anthropic":
            return self._call_anthropic(provider, prompt, system_override, **kwargs)
        else:
            # Generic OpenAI-compatible fallback
            return self._call_openai_compatible(provider, prompt, system_override, **kwargs)

    @staticmethod
    def _messages(prompt: str, system_override: str | None, history=None):
        messages = []
        if system_override:
            messages.append({"role": "system", "content": system_override})
        prompt_text = str(prompt or "").strip()
        if isinstance(history, str):
            history = []
        limit = getattr(Config, "CONVERSATION_HISTORY_TURNS", 20)
        for item in (history or [])[-limit:]:
            role = item.get("role", "user")
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            if role == "user" and content == prompt_text:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _client(self, kind: str, provider: LLMProvider, base_url: str | None = None):
        """One cached SDK client per (kind, key, base_url): built with max_retries=0 + timeout."""
        key = (kind, provider.api_key, base_url, provider.timeout)
        with self._clients_lock:
            client = self._clients.get(key)
            if client is not None:
                return client
        if kind == "groq":
            from groq import Groq
            client = Groq(api_key=provider.api_key, max_retries=0, timeout=provider.timeout)
        elif kind == "anthropic":
            try:
                import anthropic
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic") from None
            client = anthropic.Anthropic(api_key=provider.api_key, max_retries=0, timeout=provider.timeout)
        elif kind == "gemini":
            client = build_gemini_client(provider.api_key, provider.timeout)
            if client is None:
                raise ImportError("google-genai package not installed. Run: pip install google-genai")
        else:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError("openai package not installed. Run: pip install openai") from None
            kw = {"api_key": provider.api_key, "max_retries": 0, "timeout": provider.timeout}
            if base_url:
                kw["base_url"] = base_url
            client = OpenAI(**kw)
        with self._clients_lock:
            self._clients[key] = client
        return client

    def _call_groq(self, provider: LLMProvider, prompt: str, system_override: str | None = None, **kwargs) -> str:
        """Call Groq API."""
        client = self._client("groq", provider)
        messages = self._messages(prompt, system_override, kwargs.get("history"))

        with track_llm("groq", provider.model, messages=messages) as call:
            response = client.chat.completions.create(
                model=provider.model,
                messages=messages,
                max_tokens=kwargs.get("max_tokens") or provider.max_tokens,
                temperature=kwargs.get("temperature", provider.temperature),
                timeout=provider.timeout,
            )
            text = response.choices[0].message.content
            if not text or not text.strip():
                call.fail("EmptyResponse")
                return ""
            call.done(text, getattr(response, "usage", None))
        return text

    def _call_openai_compatible(self, provider: LLMProvider, prompt: str, system_override: str | None = None, base_url: str | None = None, **kwargs) -> str:
        """Call any OpenAI-compatible API (OpenAI, DeepSeek, Mistral, Together)."""
        client = self._client("openai", provider, base_url)
        messages = self._messages(prompt, system_override, kwargs.get("history"))
        label = "deepseek" if "deepseek" in (base_url or "") else "mistral" if "mistral" in (base_url or "") else "openai"
        with track_llm(label, provider.model, messages=messages) as call:
            resp = client.chat.completions.create(
                model=provider.model,
                messages=messages,
                max_tokens=kwargs.get("max_tokens") or provider.max_tokens,
                temperature=kwargs.get("temperature", provider.temperature),
                timeout=provider.timeout,
            )
            text = resp.choices[0].message.content
            if not text or not text.strip():
                call.fail("EmptyResponse")
                return ""
            call.done(text, getattr(resp, "usage", None))
        return text

    def _call_anthropic(self, provider: LLMProvider, prompt: str, system_override: str | None = None, **kwargs) -> str:
        """Call Anthropic Claude API."""
        client = self._client("anthropic", provider)
        a_messages = self._messages(prompt, None, kwargs.get("history"))
        with track_llm("anthropic", provider.model, prompt_text=(system_override or "") + "\n" + messages_text(a_messages)) as call:
            resp = client.messages.create(
                model=provider.model,
                max_tokens=kwargs.get("max_tokens") or provider.max_tokens,
                temperature=kwargs.get("temperature", provider.temperature),
                system=system_override or "",
                messages=a_messages,
                timeout=provider.timeout,
            )
            text = "".join([b.text for b in resp.content if hasattr(b, 'text')])
            if not text.strip():
                call.fail("EmptyResponse")
                return ""
            call.done(text, getattr(resp, "usage", None))
        return text

    def _call_gemini(self, provider: LLMProvider, prompt: str, system_override: str | None = None, img_path: str | None = None, **kwargs) -> str:
        """Call Gemini through the (lazily imported) google-genai SDK."""
        client = self._client("gemini", provider)
        history = kwargs.get("history") or []
        if isinstance(history, str):
            history = []
        history_text = "\n".join(
            f"{item.get('role', 'user').capitalize()}: {item.get('content', '')}"
            for item in history
            if item.get("content")
        )
        model_prompt = f"Recent conversation:\n{history_text}\n\nUser: {prompt}" if history_text else prompt
        with track_llm("gemini", provider.model, prompt_text=(system_override or "") + "\n" + model_prompt) as call:
            response = gemini_generate(
                client, provider.model, model_prompt, system_override,
                kwargs.get("max_tokens") or provider.max_tokens,
                kwargs.get("temperature", provider.temperature), img_path,
            )
            text = getattr(response, "text", None) or ""
            if not text.strip():
                call.fail("EmptyResponse")
                return ""
            call.done(text, getattr(response, "usage_metadata", None))
        return text

    def to_summary(self) -> str:
        """Human-readable summary of all providers."""
        lines = ["LLM Providers:"]
        for p in sorted(self.providers, key=lambda x: x.priority):
            status = "OK" if p.is_available else "OFF"
            key_status = "set" if p.api_key else "missing"
            lines.append(
                f"  [{status}] #{p.priority} {p.name}: {p.model} "
                f"(key={key_status}, failures={p.consecutive_failures})"
            )
        return "\n".join(lines)


# Module-level singleton
provider_manager = LLMProviderManager()

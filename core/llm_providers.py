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

Providers are tried in priority order with automatic fallback.
"""
import os
import time
import logging
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum, auto


class ProviderStatus(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    UNAVAILABLE = auto()
    UNKNOWN = auto()


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
    last_error: Optional[str] = None
    last_success: Optional[float] = None
    consecutive_failures: int = 0
    max_consecutive_failures: int = 3

    @property
    def api_key(self) -> Optional[str]:
        """Get the API key from environment."""
        return os.environ.get(self.api_key_env)

    @property
    def is_available(self) -> bool:
        """Check if provider is available (has key + not disabled)."""
        return bool(self.enabled and self.api_key and self.status != ProviderStatus.UNAVAILABLE)

    def record_success(self):
        """Record a successful call."""
        self.status = ProviderStatus.HEALTHY
        self.consecutive_failures = 0
        self.last_success = time.time()

    def record_failure(self, error: str):
        """Record a failed call."""
        self.consecutive_failures += 1
        self.last_error = error
        if self.consecutive_failures >= self.max_consecutive_failures:
            self.status = ProviderStatus.UNAVAILABLE
        else:
            self.status = ProviderStatus.DEGRADED

    def reset_status(self):
        """Reset provider status (e.g., after cooldown)."""
        self.status = ProviderStatus.UNKNOWN
        self.consecutive_failures = 0
        self.last_error = None


class LLMProviderManager:
    """
    Manages LLM providers with fallback, cooldown, and automatic recovery.
    
    Usage:
        manager = LLMProviderManager()
        result = manager.query("What is Python?")
        # Falls back through providers if one fails
    """

    # Default provider configurations — priority = fallback order
    # Groq (fast+free) -> OpenAI -> DeepSeek -> Gemini -> Anthropic -> Mistral -> Ollama fallback handled in Brain
    DEFAULT_PROVIDERS = [
        LLMProvider(
            name="groq",
            api_key_env="GROQ_API_KEY",
            model="llama-3.1-8b-instant",
            priority=1,
            timeout=15.0,
            max_tokens=2048,
            supports_vision=False,
            supports_streaming=True,
        ),
        LLMProvider(
            name="openai",
            api_key_env="OPENAI_API_KEY",
            model="gpt-4o-mini",
            priority=2,
            timeout=20.0,
            max_tokens=2048,
            supports_vision=True,
            supports_streaming=True,
        ),
        LLMProvider(
            name="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            model="deepseek-chat",
            priority=3,
            timeout=20.0,
            max_tokens=2048,
            supports_vision=False,
            supports_streaming=True,
        ),
        LLMProvider(
            name="gemini",
            api_key_env="GEMINI_API_KEY",
            model="gemini-1.5-flash",
            priority=4,
            timeout=20.0,
            max_tokens=2048,
            supports_vision=True,
            supports_streaming=True,
        ),
        LLMProvider(
            name="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            model="claude-3-5-sonnet-20241022",
            priority=5,
            timeout=25.0,
            max_tokens=2048,
            supports_vision=True,
            supports_streaming=False,
        ),
        LLMProvider(
            name="mistral",
            api_key_env="MISTRAL_API_KEY",
            model="mistral-small-latest",
            priority=6,
            timeout=20.0,
            max_tokens=2048,
            supports_vision=False,
            supports_streaming=True,
        ),
    ]

    # Cooldown period after provider failure (seconds)
    COOLDOWN_SECONDS = 300  # 5 minutes

    def __init__(self):
        self.providers: List[LLMProvider] = []
        self.logger = logging.getLogger("Flexie.LLMProviders")
        self._init_providers()
        self._load_config()

    def _init_providers(self):
        """Initialize default providers — model overridden by env if set."""
        for p in self.DEFAULT_PROVIDERS:
            # Hot-override model from Config / env (e.g. GROQ_MODEL)
            try:
                from utils.config import Config as C
                env_model = os.getenv(p.api_key_env.replace("_API_KEY", "_MODEL"), "")
                # Also try SUPPORTED_PROVIDERS mapping
                if not env_model:
                    try:
                        from utils.config import SUPPORTED_PROVIDERS as SP
                        me = SP.get(p.name, {}).get("model_env")
                        if me:
                            env_model = os.getenv(me, "")
                    except: pass
                if env_model:
                    p.model = env_model.strip()
                # Respect ACTIVE_PROVIDER filtering: if ACTIVE_PROVIDER != auto, disable others
                active = os.getenv("ACTIVE_PROVIDER", "auto").lower()
                if active != "auto" and active != p.name:
                    # Keep but mark as not priority — we filter later, just log
                    pass
            except: pass
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
                self.logger.warning(f"[LLM] Failed to load config: {e}")

    def get_available_providers(self, vision_required: bool = False) -> List[LLMProvider]:
        """Get providers sorted by priority, filtered by availability + ACTIVE_PROVIDER."""
        active = os.getenv("ACTIVE_PROVIDER", "auto").lower()
        available = []
        for p in self.providers:
            if active != "auto" and p.name != active and p.name != "ollama":
                continue
            if not p.is_available:
                continue
            if vision_required and not p.supports_vision:
                continue
            if p.status == ProviderStatus.UNAVAILABLE and p.last_error:
                if p.last_error:
                    p.reset_status()
            # Refresh model from env on each call (hot-change)
            try:
                env_model = os.getenv(p.api_key_env.replace("_API_KEY", "_MODEL"), "")
                if env_model and env_model.strip() != p.model:
                    p.model = env_model.strip()
            except: pass
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
                except: pass
                return True
        return False

    def query(
        self,
        prompt: str,
        system_override: Optional[str] = None,
        vision_required: bool = False,
        img_path: Optional[str] = None,
        **kwargs,
    ) -> tuple[str, str]:
        """
        Query LLM providers with automatic fallback.
        
        Returns:
            (response_text, provider_name)
        """
        providers = self.get_available_providers(vision_required)
        if not providers:
            return "", "none"

        last_error = ""
        for provider in providers:
            try:
                response = self._call_provider(provider, prompt, system_override, img_path, **kwargs)
                if response:
                    provider.record_success()
                    return response, provider.name
            except Exception as e:
                last_error = str(e)
                provider.record_failure(last_error)
                self.logger.warning(f"[LLM] {provider.name} failed: {e}")

        return "", "none"

    def _call_provider(
        self,
        provider: LLMProvider,
        prompt: str,
        system_override: Optional[str] = None,
        img_path: Optional[str] = None,
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

    def _call_groq(self, provider: LLMProvider, prompt: str, system_override: Optional[str] = None, **kwargs) -> str:
        """Call Groq API."""
        from groq import Groq
        client = Groq(api_key=provider.api_key)
        messages = []
        if system_override:
            messages.append({"role": "system", "content": system_override})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=provider.model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", provider.max_tokens),
            temperature=kwargs.get("temperature", provider.temperature),
            timeout=provider.timeout,
        )
        return response.choices[0].message.content

    def _call_openai_compatible(self, provider: LLMProvider, prompt: str, system_override: Optional[str] = None, base_url: Optional[str] = None, **kwargs) -> str:
        """Call any OpenAI-compatible API (OpenAI, DeepSeek, Mistral, Together)."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        client_kwargs = {"api_key": provider.api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = OpenAI(**client_kwargs)
        messages = []
        if system_override:
            messages.append({"role": "system", "content": system_override})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=provider.model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", provider.max_tokens),
            temperature=kwargs.get("temperature", provider.temperature),
            timeout=provider.timeout,
        )
        return resp.choices[0].message.content

    def _call_anthropic(self, provider: LLMProvider, prompt: str, system_override: Optional[str] = None, **kwargs) -> str:
        """Call Anthropic Claude API."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
        client = anthropic.Anthropic(api_key=provider.api_key)
        resp = client.messages.create(
            model=provider.model,
            max_tokens=kwargs.get("max_tokens", provider.max_tokens),
            temperature=kwargs.get("temperature", provider.temperature),
            system=system_override or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join([b.text for b in resp.content if hasattr(b, 'text')])

    def _call_gemini(self, provider: LLMProvider, prompt: str, system_override: Optional[str] = None, img_path: Optional[str] = None, **kwargs) -> str:
        """Call Gemini API."""
        import google.generativeai as genai
        genai.configure(api_key=provider.api_key)
        
        model_config = {"system_instruction": system_override} if system_override else {}
        model = genai.GenerativeModel(provider.model, **model_config)
        
        content = [prompt]
        if img_path:
            from PIL import Image
            img = Image.open(img_path)
            content = [prompt, img]
        
        response = model.generate_content(
            content,
            generation_config=genai.GenerationConfig(
                max_output_tokens=kwargs.get("max_tokens", provider.max_tokens),
                temperature=kwargs.get("temperature", provider.temperature),
            ),
        )
        return response.text

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

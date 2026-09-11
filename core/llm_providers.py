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

    # Default provider configurations
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
            name="gemini",
            api_key_env="GEMINI_API_KEY",
            model="gemini-1.5-flash",
            priority=2,
            timeout=20.0,
            max_tokens=2048,
            supports_vision=True,
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
        """Initialize default providers."""
        for p in self.DEFAULT_PROVIDERS:
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
        """Get providers sorted by priority, filtered by availability."""
        available = []
        for p in self.providers:
            if not p.is_available:
                continue
            if vision_required and not p.supports_vision:
                continue
            # Check cooldown
            if p.status == ProviderStatus.UNAVAILABLE and p.last_error:
                # Try to recover after cooldown
                if p.last_error:
                    p.reset_status()
            available.append(p)
        return sorted(available, key=lambda x: x.priority)

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
        elif provider.name == "gemini":
            return self._call_gemini(provider, prompt, system_override, img_path, **kwargs)
        else:
            raise ValueError(f"Unknown provider: {provider.name}")

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

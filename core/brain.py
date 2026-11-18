import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from urllib.request import Request, urlopen

# NOTE: no Google SDK is imported here. google.genai costs ~6 s of import time, so it is loaded
# on first *use* of Gemini (core.llm_providers.load_genai). The deprecated google.generativeai
# path was removed. Heavy/optional modules (PIL, requests, groq, openai, anthropic) are also
# imported only where they are used.
from core.llm_providers import build_gemini_client, gemini_generate
from core.persona import SELF_FACTS, compose_system_prompt
from core.skills import build_catalog, discover_skills
from core.telemetry.redact import redact_secrets
from core.telemetry.usage import messages_text, track_llm
from utils.config import Config
from utils.helpers import is_online

try:
    from ddgs import DDGS
except ImportError as _e:
    logging.debug("[core/brain.py] ddgs not installed: %s", _e)
    DDGS = None

logger = logging.getLogger("Flexie.Brain")

# Prompts whose answer changes by the minute are never served from the cache.
_TIME_SENSITIVE = re.compile(
    r"\b(time|date|weather|forecast|news|today|tonight|tomorrow|yesterday|now|latest|current|currently|score)\b",
    re.IGNORECASE,
)
from core.llm_failure import FAILURE_MARKERS as _FAILURE_MARKERS  # noqa: E402

_RATE_LIMIT_MARKERS = ("429", "rate limit", "too many requests")
_NETWORK_MARKERS = ("broken pipe", "connection", "timeout", "timed out")


VISION_UNAVAILABLE_MSG = (
    "I couldn't get a vision model to look at the image right now, so I can't describe it. "
    "Check your Gemini key and connection, or say 'read my screen' and I'll read the text on it instead."
)


class _Uncacheable(str):
    """A reply that must never enter the response cache (failure text, search fallback, ...)."""


def _is_failure_text(text) -> bool:
    return isinstance(text, _Uncacheable) or (
        isinstance(text, str) and any(m in text[:200] for m in _FAILURE_MARKERS)
    )


def _json_ok(text: str) -> bool:
    """True when ``text`` contains a JSON object (the shape strict-JSON callers such as the router want)."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match is None:
        return False
    try:
        return isinstance(json.loads(match.group()), dict)
    except (ValueError, TypeError):
        return False


def _wants_json(system_override) -> bool:
    low = (system_override or "").lower()
    return "valid json" in low or "only json" in low or "json only" in low


def _safe(err) -> str:
    return redact_secrets(err)


class Brain:
    _cache_lock = threading.Lock()   # the cache is touched from several threads
    _gemini_lock = threading.Lock()

    def __init__(self):
        self.gemini_model = None
        self.gemini_chat = None
        self.gemini_new_client = None
        self.gemini_model_name = getattr(Config, 'GEMINI_MODEL', 'gemini-2.0-flash')
        self.groq_client = None
        self.openai_client = None
        self.deepseek_client = None
        self.anthropic_client = None
        self.mistral_client = None
        self.system_prompt = compose_system_prompt(Config.SYSTEM_PROMPT_STANDARD) + "\n\n" + SELF_FACTS
        _skills = discover_skills()
        if _skills:
            self.system_prompt += "\n\n" + build_catalog(_skills)
        # LRU + TTL cache for recent LLM responses: key -> (stored_at, text)
        self._cache = OrderedDict()
        self._cache_max = 64
        self._cache_ttl = 45.0
        # Provider manager for fallback + dynamic provider list
        self.provider_manager = None
        try:
            from core.llm_providers import LLMProviderManager
            self.provider_manager = LLMProviderManager()
        except Exception as e:
            logging.debug("[core/brain.py] provider manager init failed: %s: %s", type(e).__name__, e)
            logger.warning("[ProviderManager Init Error]: %s", _safe(e))

        # Building the SDK clients imports openai/groq (~2 s). Do it off the startup path; the first
        # model call waits for it (bounded) so behaviour is unchanged.
        self._providers_ready = threading.Event()
        self._providers_thread = threading.Thread(target=self._init_providers_bg, name="brain-providers", daemon=True)
        self._providers_thread.start()

        # --- PHASE 2: Context Intelligence ---
        self.context_compiler = None
        self.vector_store = None
        self.memory_manager = None
        try:
            from context.compiler import ContextCompiler
            from core.vector_store import VectorStore
            self.context_compiler = ContextCompiler()
            self.vector_store = VectorStore()
        except Exception as e:
            logging.debug("[core/brain.py] context engine init failed: %s: %s", type(e).__name__, e)
            logger.warning("[Context Engine Error]: %s - Proceeding with raw context.", _safe(e))

    # ------------------------------------------------------------------ providers
    def _init_providers_bg(self):
        try:
            self._init_all_providers()
        finally:
            self._providers_ready.set()

    def _wait_providers(self):
        ready = self.__dict__.get("_providers_ready")
        if ready is not None and not ready.is_set() and threading.current_thread() is not self.__dict__.get("_providers_thread"):
            ready.wait(30.0)

    @staticmethod
    def _request_timeout() -> float:
        return float(getattr(Config, "LLM_REQUEST_TIMEOUT", 7.0) or 7.0)

    def _init_all_providers(self):
        """Initialize all LLM clients from Config (supports hot-reload).

        Every client is built with ``max_retries=0`` and an explicit timeout: the SDK's own
        retries multiplied the per-request timeout (a failing provider cost ~22 s); falling
        back to the next provider is the retry.
        """
        timeout = self._request_timeout()
        self.groq_model = getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b')
        self.groq_client = None
        if Config.GROQ_API_KEY:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=Config.GROQ_API_KEY, max_retries=0, timeout=timeout)
            except Exception as e:
                logging.debug("[core/brain.py] groq init failed: %s: %s", type(e).__name__, e)
                logger.warning("[Groq Init Error]: %s - Groq API will be disabled.", _safe(e))
                self.groq_client = None
        # Gemini: the SDK is imported and the client built lazily on first use (_get_gemini_client).
        self.gemini_model_name = getattr(Config, 'GEMINI_MODEL', 'gemini-2.0-flash')
        self.gemini_new_client = None
        self.gemini_model = None
        self.gemini_chat = None
        self._gemini_failed_key = None
        self._gemini_enabled = bool(getattr(Config, "GEMINI_API_KEY", ""))
        # OpenAI + DeepSeek + Mistral (OpenAI-compatible)
        self.openai_client = self.deepseek_client = self.mistral_client = None
        try:
            from openai import OpenAI
        except ImportError as _e:
            logging.debug("[core/brain.py] openai not installed: %s", _e)
            OpenAI = None
        if OpenAI is not None:
            for attr, key, base in (
                ("openai_client", Config.OPENAI_API_KEY, None),
                ("deepseek_client", Config.DEEPSEEK_API_KEY, "https://api.deepseek.com"),
                ("mistral_client", Config.MISTRAL_API_KEY, "https://api.mistral.ai/v1"),
            ):
                if not key:
                    continue
                try:
                    kw = {"api_key": key, "max_retries": 0, "timeout": timeout}
                    if base:
                        kw["base_url"] = base
                    setattr(self, attr, OpenAI(**kw))
                except Exception as _e:
                    logging.debug("[core/brain.py] %s init failed: %s: %s", attr, type(_e).__name__, _e)
        # Anthropic
        self.anthropic_client = None
        if Config.ANTHROPIC_API_KEY:
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(
                    api_key=Config.ANTHROPIC_API_KEY, max_retries=0, timeout=timeout)
            except Exception as e:
                logging.debug("[core/brain.py] anthropic init failed: %s: %s", type(e).__name__, e)
                logger.warning("[Anthropic Init Error]: %s", _safe(e))
                self.anthropic_client = None

    def _get_gemini_client(self):
        """Build the google-genai client on first use (keeps ``import core.brain`` ~6 s faster)."""
        client = getattr(self, "gemini_new_client", None)
        if client is not None:
            return client
        key = getattr(Config, "GEMINI_API_KEY", "")
        if not key or getattr(self, "_gemini_failed_key", None) == key:
            return None
        with self._gemini_lock:
            if getattr(self, "gemini_new_client", None) is not None:
                return self.gemini_new_client
            try:
                self.gemini_new_client = build_gemini_client(key, self._request_timeout())
            except Exception as e:
                logger.warning("[Gemini Init Error]: %s", _safe(e))
                self.gemini_new_client = None
            if self.gemini_new_client is None:
                self._gemini_failed_key = key  # don't retry the import on every call
            return self.gemini_new_client

    def _circuit_allows(self, name: str) -> bool:
        pm = getattr(self, "provider_manager", None)
        try:
            return pm.allow(name) if pm is not None else True
        except Exception:
            return True

    def _report(self, name: str, ok: bool, error: str = "") -> None:
        """Feed outcomes into the one shared circuit breaker (the provider manager's)."""
        pm = getattr(self, "provider_manager", None)
        if pm is None:
            return
        try:
            pm.report(name, ok, error)
        except Exception as _e:
            logging.debug("[core/brain.py] circuit report failed: %s", _e)

    def add_maintenance_task(self, fn, every_seconds: float = 3600.0) -> None:
        """Register a cheap callable for the maintenance thread, run at most every ``every_seconds``."""
        if not hasattr(self, "_maintenance_tasks"):
            self._maintenance_tasks = []
        self._maintenance_tasks.append([fn, float(every_seconds), 0.0])

    def _run_maintenance_once(self, now: float | None = None) -> None:
        """One maintenance tick: expired-memory cleanup, then any registered task that is due."""
        import time as _time
        now = _time.monotonic() if now is None else now
        mm = getattr(self, "memory_manager", None)
        if mm is not None:
            try:
                mm.cleanup_expired()
            except Exception as _e:
                logging.debug("[core/brain.py:maintenance] Swallowed exception: %s: %s", type(_e).__name__, _e)
        for task in list(getattr(self, "_maintenance_tasks", [])):
            fn, every, last = task
            if last and now - last < every:
                continue
            task[2] = now or 1e-9
            try:
                fn()
            except Exception as _e:
                logging.debug("[core/brain.py:maintenance] task failed: %s: %s", type(_e).__name__, _e)

    def ensure_maintenance_thread(self, interval_seconds: int = 1800) -> bool:
        """Start the periodic memory-maintenance daemon (expired cleanup).

        Runs off the read path: a daemon thread calls
        ``memory_manager.cleanup_expired()`` every ``interval_seconds``
        (default 30 min). No-op until a memory_manager is attached
        (orchestrator sets ``brain.memory_manager`` at startup).
        Returns True if the thread is (now) running.
        """
        if getattr(self, "_maintenance_started", False):
            return True
        self._maintenance_started = True

        def _loop():
            import time as _time
            while True:
                try:
                    _time.sleep(interval_seconds)
                    self._run_maintenance_once()
                except Exception as _e:
                    logging.debug("[core/brain.py:maintenance] Swallowed exception: %s: %s", type(_e).__name__, _e)

        import threading as _threading
        t = _threading.Thread(target=_loop, daemon=True, name="brain-maintenance")
        t.start()
        return True

    def reload_providers(self):
        """Hot-reload all providers after API key change via UI (no restart needed)."""
        from utils.config import Config as C
        C.reload()
        self._wait_providers()
        self._init_all_providers()
        with self._cache_lock:
            if getattr(self, "_cache", None) is not None:
                self._cache.clear()
        # Also refresh provider_manager
        if self.provider_manager:
            try:
                from core.llm_providers import LLMProviderManager
                self.provider_manager = LLMProviderManager()
            except Exception as _e:
                logging.debug("[core/brain.py] provider manager reload failed: %s", _e)
        logger.info("[Brain] Providers reloaded from .env")

    def get_provider_status(self) -> dict:
        """Return status dict for UI badges."""
        from utils.config import Config as C
        return C.get_all_keys_masked()

    # ------------------------------------------------------------------ messages
    @staticmethod
    def _normalize_history(history):
        if isinstance(history, str):
            return []
        return history or []

    @staticmethod
    def _history_key(history):
        history = Brain._normalize_history(history)
        if not history:
            return ()
        limit = getattr(Config, "CONVERSATION_HISTORY_TURNS", 20)
        return tuple(
            (str(item.get("role", "user")), str(item.get("content", "")))
            for item in history[-limit:]
        )

    @staticmethod
    def _build_messages(sys_p: str, prompt: str, history=None):
        messages = []
        if sys_p:
            messages.append({"role": "system", "content": sys_p})
        prompt_text = str(prompt or "").strip()
        limit = getattr(Config, "CONVERSATION_HISTORY_TURNS", 20)
        for item in Brain._normalize_history(history)[-limit:]:
            role = item.get("role", "user")
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            if role == "user" and content == prompt_text:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _history_as_text(history):
        return "\n".join(
            f"{item.get('role', 'user').capitalize()}: {item.get('content', '')}"
            for item in Brain._normalize_history(history)
            if item.get("content")
        )

    def _provider_for_client(self, client) -> str:
        if client is not None and client is getattr(self, "groq_client", None):
            return "groq"
        if client is not None and client is getattr(self, "deepseek_client", None):
            return "deepseek"
        if client is not None and client is getattr(self, "mistral_client", None):
            return "mistral"
        return "openai"

    # ------------------------------------------------------------------ single-provider calls
    def _ask_openai_compatible(self, client, model: str, prompt: str, sys_p: str, max_tokens: int | None = None, history=None) -> str | None:
        """One OpenAI-style call (OpenAI, DeepSeek, Mistral, Groq). None on error or empty reply."""
        if not client:
            return None
        label = self._provider_for_client(client)
        try:
            kwargs = dict(model=model, messages=self._build_messages(sys_p, prompt, history), timeout=self._request_timeout())
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            with track_llm(label, model, messages=kwargs["messages"]) as call:
                resp = client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content
                if not text or not text.strip():
                    # e.g. Groq reasoning tokens consumed max_tokens: an empty reply is a failure
                    call.fail("EmptyResponse")
                    return None
                call.done(text, getattr(resp, "usage", None))
            return text
        except Exception as e:
            logging.debug("[core/brain.py] %s call failed: %s: %s", label, type(e).__name__, e)
            logger.warning("[%s Error (%s)]: %s", label, model, _safe(e))
            return None

    def _ask_anthropic(self, prompt: str, sys_p: str, history=None, max_tokens: int | None = None) -> str | None:
        if not self.anthropic_client:
            return None
        try:
            anthropic_model = getattr(Config, 'ANTHROPIC_MODEL', 'claude-sonnet-4-20250514')
            a_messages = self._build_messages("", prompt, history)
            with track_llm("anthropic", anthropic_model, prompt_text=sys_p + "\n" + messages_text(a_messages)) as call:
                resp = self.anthropic_client.messages.create(
                    model=anthropic_model, max_tokens=max_tokens or 2048, system=sys_p, messages=a_messages,
                    timeout=self._request_timeout(),
                )
                text = "".join([b.text for b in resp.content if hasattr(b, 'text')])
                if not text.strip():
                    call.fail("EmptyResponse")
                    return None
                call.done(text, getattr(resp, "usage", None))
            return text
        except Exception as e:
            logging.debug("[core/brain.py] anthropic call failed: %s: %s", type(e).__name__, e)
            logger.warning("[Anthropic Error]: %s", _safe(e))
            return None

    _GEMINI_FALLBACK_MODELS = ("gemini-flash-latest", "gemini-3.8-flash")

    def _ask_gemini(self, prompt: str, sys_p: str, max_tokens: int | None, history, img_path: str | None) -> str | None:
        client = self._get_gemini_client()
        if client is None:
            return None
        gname = getattr(self, "_gemini_working_model", None) or getattr(
            Config, 'GEMINI_MODEL', getattr(self, 'gemini_model_name', 'gemini-flash-latest'))
        history_text = self._history_as_text(history)
        text_in = (f"Recent conversation:\n{history_text}\n\nUser: {prompt}"
                   if history_text else prompt)
        tried = []
        candidates = [gname] + [m for m in self._GEMINI_FALLBACK_MODELS if m != gname]
        for model in candidates:
            tried.append(model)
            try:
                with track_llm("gemini", model, prompt_text=sys_p + "\n" + text_in) as call:
                    # the system prompt is ALWAYS sent as the system instruction (even when it is the default)
                    resp = gemini_generate(client, model, text_in, sys_p, max_tokens, None, img_path)
                    text = getattr(resp, 'text', None) or ""
                    if not text.strip():
                        call.fail("EmptyResponse")
                        return None
                    call.done(text, getattr(resp, "usage_metadata", None))
                self._gemini_working_model = model  # remember the model that works
                return text
            except Exception as e:
                msg = str(e)
                logging.debug("[core/brain.py] gemini call failed: %s: %s", type(e).__name__, e)
                logger.warning("[Gemini Error (%s)]: %s - Falling back", model, _safe(e))
                # A retired / unknown / overloaded model: try the next known-good model name. Anything else
                # (quota, network, bad key) goes straight to the next provider.
                if not ("NOT_FOUND" in msg or "no longer available" in msg or " 404" in msg
                        or "UNAVAILABLE" in msg or " 503" in msg):
                    return None
        return None

    def _provider_sig(self):
        """What can change an answer besides the prompt: provider choice, engine and model names.
        Part of the cache key so switching provider/model never replays another model's answer."""
        names = ("GROQ_MODEL", "OPENAI_MODEL", "OLLAMA_MODEL", "DEEPSEEK_MODEL", "MISTRAL_MODEL",
                 "GEMINI_MODEL", "ANTHROPIC_MODEL")
        try:
            active = self._active_provider()
        except Exception:
            active = "auto"
        return (active, str(getattr(Config, "ENGINE", "auto")),
                tuple(str(getattr(Config, n, "") or "") for n in names))

    @staticmethod
    def _img_sig(img_path):
        try:
            st = os.stat(img_path)
            return (os.path.abspath(img_path), st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _cache_key(self, prompt, img_path, system_override, use_chat, use_rag, max_tokens, history):
        """None means "do not cache": time-sensitive prompts and unreadable images."""
        if _TIME_SENSITIVE.search(str(prompt or "")):
            return None
        img = None
        if img_path:
            img = self._img_sig(img_path)
            if img is None:
                return None
        return (prompt, system_override or self.system_prompt, use_rag, max_tokens,
                self._history_key(history), img, bool(use_chat), self._provider_sig())

    def _cache_get(self, key):
        ttl = getattr(self, "_cache_ttl", 45.0)
        with self._cache_lock:
            item = self._cache.get(key)
            if item is None:
                return None
            stored_at, text = item
            if time.monotonic() - stored_at > ttl:
                self._cache.pop(key, None)
                return None
            if hasattr(self._cache, "move_to_end"):
                self._cache.move_to_end(key)
            return text

    def _cache_put(self, key, text):
        limit = getattr(self, "_cache_max", 64)
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), text)
            while len(self._cache) > limit:
                try:
                    del self._cache[next(iter(self._cache))]
                except (StopIteration, KeyError):
                    break

    # ------------------------------------------------------------------ ask
    def ask(self, prompt: str, img_path: str | None = None, system_override: str | None = None, use_chat: bool = False, use_rag: bool = True, max_tokens: int | None = None, history=None, expect_json: bool = False, validate=None, skip_local: bool = False) -> str:
        """Query the AI brain, with a short-lived LRU cache and optional RAG.

        ``expect_json`` / ``validate`` make a provider's reply acceptable only if it parses (a callable
        ``validate(text) -> bool``); an invalid or empty reply moves on to the next provider. A system
        prompt that says "valid JSON" turns ``expect_json`` on automatically.

        Failures (no provider answered, search fallback) are never cached; answers expire after
        ``_cache_ttl`` seconds and time-sensitive prompts bypass the cache entirely.
        """
        self._wait_providers()
        key = self._cache_key(prompt, img_path, system_override, use_chat, use_rag, max_tokens, history)
        if key is not None:
            hit = self._cache_get(key)
            if hit is not None:
                return hit

        validator = validate or (_json_ok if (expect_json or _wants_json(system_override)) else None)
        extra = {}
        if validator is not None:
            extra["validate"] = validator
        if skip_local:
            extra["skip_local"] = True

        result = ""
        for attempt in range(2):
            try:
                result = self._ask_impl(prompt, img_path, system_override, use_chat, use_rag, max_tokens, history, **extra)
                break
            except Exception as e:
                err = str(e).lower()
                rate_limited = any(m in err for m in _RATE_LIMIT_MARKERS)
                transient = any(m in err for m in _NETWORK_MARKERS)
                # fail fast: one very short retry for a transient network blip, never for rate limits
                if attempt == 0 and transient and not rate_limited:
                    time.sleep(0.25)
                    continue
                raise

        if key is not None and isinstance(result, str) and result.strip() and not _is_failure_text(result):
            self._cache_put(key, result)
        return result

    def _local_first_enabled(self, active: str) -> bool:
        engine_pref = getattr(Config, "ENGINE", "auto")
        local_enabled = engine_pref == "ollama" or (
            engine_pref == "auto" and getattr(Config, "LOCAL_FIRST", True)
        )
        return bool(local_enabled and active in ("auto", "ollama"))

    @staticmethod
    def _active_provider() -> str:
        return str(getattr(Config, 'ACTIVE_PROVIDER', 'auto') or 'auto').lower()

    def _ask_impl(self, prompt: str, img_path: str | None, system_override: str | None, use_chat: bool, use_rag: bool, max_tokens: int | None = None, history=None, validate=None, skip_local: bool = False) -> str:
        """Core ask logic (caching is handled by ask()).

        Returns an ``_Uncacheable`` string for anything that is not a real model answer.
        """
        sys_p = system_override or self.system_prompt

        if use_rag and self.context_compiler and self.vector_store and getattr(self.vector_store, "rag_available", True):
            try:
                episodes = self.vector_store.search_episodes(prompt, limit=5)
                historical_data = "\n".join([str(e) for e in episodes]) if episodes else ""
                mm_entries: list = []
                if hasattr(self, 'memory_manager') and self.memory_manager:
                    try:
                        from core.memory_manager import MemoryCategory
                        mm_hits = self.memory_manager.search(
                            prompt, limit=5, exclude_categories=[MemoryCategory.CONVERSATION])
                        if mm_hits:
                            # Structured entries: the compiler drops CONVERSATION ones (MM-10).
                            mm_entries = list(mm_hits)
                        # NOTE: expired-memory cleanup runs on the maintenance
                        # thread (see ensure_maintenance_thread), never here.
                    except Exception as _e:
                        logging.debug("[core/brain.py] memory search failed: %s", _e)
                sys_p = self.context_compiler.compile(
                    sys_p, {"memory": historical_data, "memory_entries": mm_entries})
            except Exception as e:
                logging.debug("[core/brain.py] context compilation failed: %s: %s", type(e).__name__, e)
                logger.warning("[Context Compilation Warning]: %s", _safe(e))

        invalid: list[str] = []  # first non-empty reply that failed validation (last-resort answer)

        def accept(text) -> bool:
            if not isinstance(text, str) or not text.strip():
                return False  # empty / whitespace is never an answer
            if validate is not None:
                try:
                    ok = bool(validate(text))
                except Exception:
                    ok = False
                if not ok:
                    if not invalid:
                        invalid.append(text)
                    return False
            return True

        active = self._active_provider()

        # Local-first: try Ollama before any cloud provider when enabled.
        if not skip_local and not img_path and self._local_first_enabled(active):
            timeout = float(getattr(Config, "LOCAL_JSON_TIMEOUT", 6.0)) if validate is not None \
                else float(getattr(Config, "LOCAL_LLM_TIMEOUT", 30.0))
            local = self._ask_local_engine(prompt, sys_p, max_tokens, history, timeout=timeout)
            if accept(local):
                return local

        online = is_online()
        tried: set[str] = set()
        if online:
            # (name, call) in fallback order, only for providers that have a client. Each call returns
            # text or None and never raises.
            def _oc(client, model):
                return lambda: self._ask_openai_compatible(client, model, prompt, sys_p, max_tokens, history)

            chain = []
            groq_client = getattr(self, "groq_client", None)
            if groq_client:
                # Groq has a tight TPM ceiling (~8 000 tokens/min on free tier): skip huge prompts.
                chars = len(prompt) + len(sys_p) + sum(len(str(m)) for m in (history or []))
                if chars > 20000:
                    logger.info("[Groq] Skipping oversized prompt (%d chars) - trying next provider", chars)
                    tried.add("groq")
                else:
                    main_model = getattr(self, 'groq_model', getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b'))
                    chain.append(("groq", _oc(groq_client, main_model)))
                    # Groq rate limits (and tool-call glitches) are per MODEL: try its sibling models
                    # before giving up on the provider.
                    for alt in getattr(Config, "GROQ_FALLBACK_MODELS", ()):
                        if alt != main_model:
                            chain.append(("groq", _oc(groq_client, alt)))
            for pname, attr, cfg, default in (
                ("openai", "openai_client", "OPENAI_MODEL", "gpt-4o-mini"),
                ("deepseek", "deepseek_client", "DEEPSEEK_MODEL", "deepseek-chat"),
                ("mistral", "mistral_client", "MISTRAL_MODEL", "mistral-small-latest"),
            ):
                client = getattr(self, attr, None)
                if client:
                    chain.append((pname, _oc(client, getattr(Config, cfg, default))))
            if getattr(self, "_gemini_enabled", False) or getattr(self, "gemini_new_client", None) is not None:
                chain.append(("gemini", lambda: self._ask_gemini(prompt, sys_p, max_tokens, history, img_path)))
            if getattr(self, "anthropic_client", None):
                chain.append(("anthropic", lambda: self._ask_anthropic(prompt, sys_p, history, max_tokens)))

            if img_path:
                # Text-only models never see the image and would invent a description: only
                # providers that really receive it may answer.
                tried.update(n for n, _ in chain if n != "gemini")
                chain = [(n, c) for n, c in chain if n == "gemini"]

            for name, call in chain:
                if active not in ("auto", name) or not self._circuit_allows(name):
                    continue
                tried.add(name)
                text = call()
                self._report(name, bool(text and str(text).strip()), "" if text else "no result")
                if accept(text):
                    return text

            if self.provider_manager:
                try:
                    resp, _pname = self.provider_manager.query(
                        prompt, system_override=sys_p, img_path=img_path, history=history,
                        max_tokens=max_tokens, exclude=tried, vision_required=bool(img_path))
                    if accept(resp):
                        return resp
                except Exception as _e:
                    logging.debug("[core/brain.py] provider manager failed: %s: %s", type(_e).__name__, _e)
            if img_path:
                # Never answer an image question with text-only guesses or a web search.
                return _Uncacheable(VISION_UNAVAILABLE_MSG)
            # A specific cloud provider was requested but failed: skip the local reasoning chain.
            if active not in ('auto', 'ollama'):
                return self._final_failure(prompt, online, validate, invalid)

        if img_path:  # offline, or no cloud vision answered: the local text models cannot see images
            return _Uncacheable(VISION_UNAVAILABLE_MSG)

        # Local Ollama reasoning (deepseek-r1) - preferred when available
        try:
            ollama_reason = self._ollama_reasoning(prompt, sys_p, history)
            if accept(ollama_reason):
                return ollama_reason
        except Exception as e:
            logging.debug("[core/brain.py] Ollama reasoning swallowed: %s", e)
        ollama_res = self._ask_ollama(prompt)
        if accept(ollama_res):
            return ollama_res
        return self._final_failure(prompt, online, validate, invalid)

    def _final_failure(self, prompt: str, online: bool, validate, invalid: list[str]) -> str:
        """Everything failed. The result is flagged uncacheable so the failure is never replayed."""
        if invalid:
            return _Uncacheable(invalid[0])  # a reply the validator disliked beats nothing; caller falls back
        if validate is not None:
            return _Uncacheable("")  # strict-format callers want "no answer", not search prose
        if online:
            return _Uncacheable(self._ddg_search(prompt))
        return _Uncacheable("All AI providers are unavailable right now — online LLMs and local Ollama both failed. Check your internet connection or start Ollama if you'd like local processing.")

    # ------------------------------------------------------------------ streaming
    def _stream_chat(self, label: str, client, model: str, messages: list, max_tokens: int | None):
        """Yield text deltas from an OpenAI-style streaming endpoint.

        The telemetry timer starts BEFORE the request, and exact usage is requested
        (``stream_options.include_usage``) where the SDK/server supports it.
        """
        kwargs = dict(model=model, messages=messages, stream=True, timeout=self._request_timeout())
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        streamed: list[str] = []
        usage = None
        with track_llm(label, model, messages=messages) as call:
            try:
                try:
                    stream = client.chat.completions.create(stream_options={"include_usage": True}, **kwargs)
                except TypeError:
                    stream = client.chat.completions.create(**kwargs)
                except Exception as e:
                    if "stream_options" not in str(e).lower():
                        raise
                    stream = client.chat.completions.create(**kwargs)
                for chunk in stream:
                    usage = getattr(chunk, "usage", None) or getattr(getattr(chunk, "x_groq", None), "usage", None) or usage
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue  # the final usage-only chunk has no choices
                    delta_obj = getattr(choices[0], "delta", None)
                    delta = getattr(delta_obj, "content", None) if delta_obj else None
                    if delta:
                        streamed.append(delta)
                        yield delta
            except GeneratorExit:  # consumer stopped early: record what was produced
                call.done("".join(streamed), usage)
                raise
            if not streamed:
                call.fail("EmptyStream")
            else:
                call.done("".join(streamed), usage)

    def ask_stream(self, prompt: str, system_override: str | None = None, use_rag: bool = False, max_tokens: int | None = None, history=None):
        """Streaming version - yields text chunks as they arrive.

        Local-first like ask(). Once the first chunk has been yielded the stream NEVER falls back to a
        different provider (that would repeat the answer): it finishes or stops cleanly. If nothing was
        yielded the non-streaming ask() chain runs.
        """
        self._wait_providers()
        sys_p = system_override or self.system_prompt
        active = self._active_provider()
        messages = self._build_messages(sys_p, prompt, history)
        local_model = getattr(Config, "OLLAMA_MODEL", None) or "llama3.2:3b"
        sources: list[tuple[str, object]] = []
        local_listed = False

        def _local():
            return self._ollama_chat_stream(local_model, messages)

        if self._local_first_enabled(active) and self._ollama_available():
            sources.append(("ollama", _local))
            local_listed = True
        if is_online():
            for name, client, model in (
                ("groq", getattr(self, "groq_client", None), getattr(self, 'groq_model', getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b'))),
                ("openai", getattr(self, "openai_client", None), getattr(Config, 'OPENAI_MODEL', 'gpt-4o-mini')),
                ("deepseek", getattr(self, "deepseek_client", None), getattr(Config, 'DEEPSEEK_MODEL', 'deepseek-chat')),
                ("mistral", getattr(self, "mistral_client", None), getattr(Config, 'MISTRAL_MODEL', 'mistral-small-latest')),
            ):
                if client and active in ("auto", name) and self._circuit_allows(name):
                    sources.append((name, lambda n=name, c=client, m=model: self._stream_chat(n, c, m, messages, max_tokens)))
        if not local_listed and active in ("auto", "ollama") and self._ollama_available():
            sources.append(("ollama", _local))
            local_listed = True

        yielded = False
        for name, make in sources:
            try:
                for delta in make():
                    yielded = True
                    yield delta
            except Exception as e:
                logging.debug("[core/brain.py] %s stream failed: %s: %s", name, type(e).__name__, e)
                logger.warning("[%s Stream Error]: %s", name, _safe(e))
                if name != "ollama":
                    self._report(name, False, str(e))
                if yielded:
                    return  # partial answer already delivered: stop cleanly, no duplicate fallback
                continue
            if yielded:
                if name != "ollama":
                    self._report(name, True)
                return
        # Nothing streamed: run the non-streaming chain (skip local if it was already tried).
        reply = self.ask(prompt, system_override=system_override, use_rag=use_rag, max_tokens=max_tokens,
                         history=history, skip_local=local_listed)
        yield reply

    def react(self, prompt: str, tool_registry=None, max_steps: int = 5) -> str:
        """Run a ReAct agent loop — reason, act with tools, observe, reflect."""
        try:
            from core.agent_loop import ReActAgent
            agent = ReActAgent(tool_registry=tool_registry, max_steps=max_steps)
            return agent.run(prompt)
        except Exception as e:
            logging.debug("[core/brain.py:react] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"Agent error: {e}. Falling back to direct response."

    # ------------------------------------------------------------------ local (Ollama)
    def _ask_local_engine(self, prompt: str, sys_p: str, max_tokens: int | None, history=None, timeout: float | None = None) -> str | None:
        """Ask the local Ollama engine through the inference registry.

        Messages are assembled exactly like the cloud path (history limit, role filtering, no
        duplicate of the current prompt). An empty/whitespace answer is never returned.
        """
        try:
            from core.inference import OllamaEngine

            engine = OllamaEngine(timeout=timeout) if timeout else OllamaEngine()
            if not engine.available():
                return None
            result = engine.generate(
                self._build_messages(sys_p, prompt, history),
                model=getattr(Config, "OLLAMA_MODEL", None),
                max_tokens=max_tokens or 2048,
            )
            if result.text and result.text.strip():
                logger.info("[Local] Answered with %s", result.model)
                return result.text
        except Exception as e:
            logging.debug("[core/brain.py:local] Swallowed exception: %s: %s", type(e).__name__, e)
        return None

    def _ask_ollama(self, prompt: str) -> str | None:
        """Tries to get a response from a local Ollama instance."""
        if not self._ollama_available():
            return None
        try:
            import requests
            payload = {
                "model": Config.OLLAMA_MODEL,
                "prompt": f"{self.system_prompt}\n\nUser: {prompt}\n{Config.NAME}:",
                "stream": False
            }
            response = requests.post(Config.OLLAMA_URL, json=payload, timeout=10)
            if response.status_code == 200:
                text = response.json().get("response", "").strip()
                return text or None
            err_msg = response.json().get("error", "Unknown Ollama Error")
            logger.warning("[Ollama Error %s]: %s", response.status_code, _safe(err_msg))
        except Exception as e:
            logging.debug("[core/brain.py] ollama request failed: %s: %s", type(e).__name__, e)
            logger.warning("[Ollama Connection Error]: %s", _safe(e))
        return None

    @staticmethod
    def _ollama_base() -> str:
        """The Ollama host (scheme://netloc) derived from Config.OLLAMA_URL (shared helper)."""
        try:
            from core.inference.ollama import ollama_base_url
            return ollama_base_url()
        except Exception as _e:
            logging.debug("[core/brain.py:ollama_base] Swallowed exception: %s: %s", type(_e).__name__, _e)
        return "http://localhost:11434"

    def _ollama_available(self) -> bool:
        """Is a local Ollama server running? Uses the ONE shared health cache (30 s TTL)."""
        try:
            from core.inference.ollama import ollama_available
            return ollama_available(self._ollama_base(), opener=urlopen, timeout=0.8)
        except Exception:
            return False

    def _ollama_chat_stream(self, model: str, messages: list, temperature: float = 0.7):
        """Stream tokens from a local Ollama chat endpoint.

        Errors PROPAGATE (the caller decides whether a fallback is still safe); an empty stream is
        recorded as a failure so the caller can fall back to the non-streaming path.
        """
        payload = {"model": model, "messages": messages, "stream": True, "options": {"temperature": temperature}}
        req = Request(f"{self._ollama_base()}/api/chat", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        streamed: list[str] = []
        with track_llm("ollama", model, messages=messages) as call:
            try:
                with urlopen(req, timeout=15) as resp:
                    for line in resp:
                        line = line.decode().strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("error"):
                            raise RuntimeError(str(obj["error"]))
                        if obj.get("done"):
                            if streamed:
                                call.done("".join(streamed), obj)  # final chunk carries exact counts
                            else:
                                call.fail("EmptyStream")
                            return
                        content = (obj.get("message") or {}).get("content", "")
                        if content:
                            streamed.append(content)
                            yield content
            except GeneratorExit:
                call.done("".join(streamed), None)
                raise
            if streamed:
                call.done("".join(streamed), None)
            else:
                call.fail("EmptyStream")

    def _ollama_reasoning(self, prompt: str, system_prompt: str = None, history=None) -> str:
        """Use a local reasoning model (deepseek-r1) for plan/think steps."""
        if not self._ollama_available():
            return None
        model = getattr(Config, "OLLAMA_REASONING_MODEL", "deepseek-r1")
        messages = self._build_messages(
            system_prompt or "You are a reasoning assistant. Think step by step before answering.",
            prompt,
            history,
        )

        try:
            payload = {"model": model, "messages": messages, "stream": False,
                       "options": {"temperature": 0.3, "num_predict": 1024}}
            req = Request(f"{self._ollama_base()}/api/chat", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
            with track_llm("ollama", model, messages=messages) as call:
                with urlopen(req, timeout=60) as resp:
                    obj = json.loads(resp.read().decode())
                text = (obj.get("message") or {}).get("content", "")
                if not text or not text.strip():
                    call.fail("EmptyResponse")
                    return None
                call.done(text, obj)  # Ollama returns exact prompt_eval_count / eval_count
            return text
        except Exception as e:
            logging.debug("[core/brain.py:ollama_reasoning] Swallowed exception: %s: %s", type(e).__name__, e)
            return None

    # ------------------------------------------------------------------ fallbacks / helpers
    def _ddg_search(self, prompt: str) -> str:
        """Web-search fallback via ddgs, with timeout and friendly fallback."""
        if DDGS is None:
            return f"I've searched for you, {Config.USER_NAME}, but I couldn't find a clear enough summary to read back. I've opened the browser results for you."
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    results = list(ddgs.text(prompt, max_results=3, safesearch='on', timeout=10))
                    if results:
                        body = results[0].get("body", "")
                        body = "".join(char for char in body if char.isprintable())
                        body = re.sub(r'http\S+', '', body)
                        if len(body.strip()) > 5:
                            return f"Based on my web search, {body.strip()[:380]}..."
        except Exception as e:
            logging.debug("[core/brain.py] ddg search failed: %s: %s", type(e).__name__, e)
            logger.warning("[Brain Error]: %s", _safe(e))
        return f"I've searched for you, {Config.USER_NAME}, but I couldn't find a clear enough summary to read back. I've opened the browser results for you."

    def _ask_ddg(self, prompt: str) -> str:
        """Back-compat alias for the DuckDuckGo fallback (see _ddg_search)."""
        return self._ddg_search(prompt)

    def translate(self, text: str, dest_lang: str) -> str:
        # Use AI for translation - much more reliable than googletrans
        return self.ask(f"Translate the following text to {dest_lang}. Only return the translated text: {text}")

    def summarize_error(self, traceback_str: str) -> str:
        try:
            return self.ask(f"Summarize this Python error in one clear, helpful sentence for a developer: {traceback_str}")
        except Exception as _e:
            logging.debug("[core/brain.py:360] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return f"An internal error occurred: {traceback_str[:100]}..."

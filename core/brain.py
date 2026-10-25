import warnings
# Suppress FutureWarning from google.generativeai before any google imports
warnings.filterwarnings("ignore", category=FutureWarning)
import logging
import json
from collections import OrderedDict
from urllib.request import urlopen, Request

# google-genai (new SDK) is the only supported Gemini path.
# Legacy google-generativeai was removed from requirements; kept as
# best-effort fallback only if still installed.
try:
    from google import genai as genai_new
    _USE_NEW_GENAI = True
except ImportError as _e:
    logging.debug("[core/brain.py:9] Swallowed exception: %s: %s", type(_e).__name__, _e)
    genai_new = None
    _USE_NEW_GENAI = False
try:
    import google.generativeai as genai_legacy
except ImportError as _e:
    logging.debug("[core/brain.py:14] Swallowed exception: %s: %s", type(_e).__name__, _e)
    genai_legacy = None
# Back-compat alias: code below prefers genai_new, falls back to genai_legacy.
genai = genai_legacy
try:
    from groq import Groq
except ImportError as e:
    logging.debug("[core/brain.py:21] Swallowed exception: %s: %s", type(e).__name__, e)
    print(f"[Groq Import Error]: {e} - Groq API will be disabled.")
    Groq = None
import requests
from PIL import Image
try:
    from ddgs import DDGS
except ImportError as _e:
    logging.debug("[core/brain.py:29] Swallowed exception: %s: %s", type(_e).__name__, _e)
    DDGS = None
import re
from typing import Optional
from utils.config import Config
from utils.helpers import is_online

class Brain:
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
        self.system_prompt = Config.SYSTEM_PROMPT_STANDARD
        # LRU cache for recent LLM responses (prompt + prompt key -> response)
        self._cache = OrderedDict()
        self._cache_max = 64
        # Provider manager for fallback + dynamic provider list
        self.provider_manager = None
        try:
            from core.llm_providers import LLMProviderManager
            self.provider_manager = LLMProviderManager()
        except Exception as e:
            logging.debug("[core/brain.py:51] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[ProviderManager Init Error]: {e}")
        
        self._init_all_providers()
        
        # --- PHASE 2: Context Intelligence ---
                
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
            logging.debug("[core/brain.py:67] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[Context Engine Error]: {e} - Proceeding with raw context.")

    def _init_all_providers(self):
        """Initialize all LLM clients from Config (supports hot-reload)."""
        # Groq (model from Config.GROQ_MODEL) - Sep 2026: Groq decommissioned llama-* , current valid: openai/gpt-oss-20b
        if Config.GROQ_API_KEY and Groq:
            try:
                self.groq_client = Groq(api_key=Config.GROQ_API_KEY)
                self.groq_model = getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b')
            except Exception as e:
                logging.debug("[core/brain.py:77] Swallowed exception: %s: %s", type(e).__name__, e)
                print(f"[Groq Init Error]: {e}")
                self.groq_client = None
        else:
            self.groq_client = None
            self.groq_model = getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b')
        # Gemini via new google-genai SDK (preferred). Legacy SDK only if still installed.
        gemini_model_name = getattr(Config, 'GEMINI_MODEL', 'gemini-2.0-flash')
        self.gemini_model_name = gemini_model_name
        self.gemini_new_client = None
        self.gemini_model = None
        self.gemini_chat = None
        if Config.GEMINI_API_KEY:
            if genai_new is not None:
                try:
                    self.gemini_new_client = genai_new.Client(api_key=Config.GEMINI_API_KEY)
                except Exception as e:
                    logging.debug("[core/brain.py:91] Swallowed exception: %s: %s", type(e).__name__, e)
                    print(f"[Gemini Init Error]: {e}")
                    self.gemini_new_client = None
            if self.gemini_new_client is None and genai_legacy is not None:
                try:
                    genai_legacy.configure(api_key=Config.GEMINI_API_KEY)
                    self.gemini_model = genai_legacy.GenerativeModel(gemini_model_name, system_instruction=self.system_prompt)
                    self.gemini_chat = self.gemini_model.start_chat()
                except Exception as e:
                    logging.debug("[core/brain.py:91] Swallowed exception: %s: %s", type(e).__name__, e)
                    print(f"[Gemini Init Error]: {e}")
                    self.gemini_model = None
        # OpenAI + DeepSeek + Mistral (OpenAI-compatible)
        try:
            from openai import OpenAI
            if Config.OPENAI_API_KEY:
                try: self.openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
                except Exception as _e:
                    logging.debug("[core/brain.py:103] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    self.openai_client = None
            else: self.openai_client = None
            if Config.DEEPSEEK_API_KEY:
                try: self.deepseek_client = OpenAI(api_key=Config.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
                except Exception as _e:
                    logging.debug("[core/brain.py:107] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    self.deepseek_client = None
            else: self.deepseek_client = None
            if Config.MISTRAL_API_KEY:
                try: self.mistral_client = OpenAI(api_key=Config.MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1")
                except Exception as _e:
                    logging.debug("[core/brain.py:111] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    self.mistral_client = None
            else: self.mistral_client = None
        except ImportError as _e:
            logging.debug("[core/brain.py:113] Swallowed exception: %s: %s", type(_e).__name__, _e)
            self.openai_client = self.deepseek_client = self.mistral_client = None
        # Anthropic
        if Config.ANTHROPIC_API_KEY:
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
            except Exception as e:
                logging.debug("[core/brain.py:120] Swallowed exception: %s: %s", type(e).__name__, e)
                print(f"[Anthropic Init Error]: {e}")
                self.anthropic_client = None
        else:
            self.anthropic_client = None

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
                    mm = getattr(self, "memory_manager", None)
                    if mm is not None:
                        try:
                            mm.cleanup_expired()
                        except Exception as _e:
                            logging.debug("[core/brain.py:maintenance] Swallowed exception: %s: %s", type(_e).__name__, _e)
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
        self._init_all_providers()
        # Also refresh provider_manager
        if self.provider_manager:
            try:
                from core.llm_providers import LLMProviderManager
                self.provider_manager = LLMProviderManager()
            except Exception as _e:
                logging.debug("[core/brain.py:136] Swallowed exception: %s: %s", type(_e).__name__, _e)
        print("[Brain] Providers reloaded from .env")

    def get_provider_status(self) -> dict:
        """Return status dict for UI badges."""
        from utils.config import Config as C
        return C.get_all_keys_masked()

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

    def _ask_openai_compatible(self, client, model: str, prompt: str, sys_p: str, max_tokens: Optional[int] = None, history=None) -> Optional[str]:
        if not client:
            return None
        try:
            kwargs = dict(model=model, messages=self._build_messages(sys_p, prompt, history), timeout=Config.LLM_REQUEST_TIMEOUT)
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            logging.debug("[core/brain.py:154] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[OpenAI-Compatible Error ({model})]: {e}")
            return None

    def _ask_anthropic(self, prompt: str, sys_p: str, history=None) -> Optional[str]:
        if not self.anthropic_client:
            return None
        try:
            anthropic_model = getattr(Config, 'ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
            resp = self.anthropic_client.messages.create(
                model=anthropic_model, max_tokens=2048, system=sys_p,
                messages=self._build_messages("", prompt, history)
            )
            return "".join([b.text for b in resp.content if hasattr(b, 'text')])
        except Exception as e:
            logging.debug("[core/brain.py:168] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[Anthropic Error]: {e}")
            return None

    def ask(self, prompt: str, img_path: Optional[str] = None, system_override: Optional[str] = None, use_chat: bool = False, use_rag: bool = True, max_tokens: Optional[int] = None, history=None) -> str:
        """Query the AI brain, with LRU caching and optional RAG. Includes rate-limit retry logic."""
        key = (prompt, system_override or self.system_prompt, use_rag, max_tokens, self._history_key(history))
        if key in self._cache:
            return self._cache[key]
            
        import time
        max_attempts = 4
        result = ""
        for attempt in range(max_attempts):
            try:
                result = self._ask_impl(prompt, img_path, system_override, use_chat, use_rag, max_tokens, history)
                break
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "rate limit" in err_str or "too many requests" in err_str
                is_network_err = "broken pipe" in err_str or "connection" in err_str or "timeout" in err_str
                if is_rate_limit or is_network_err:
                    if attempt < max_attempts - 1:
                        sleep_time = (attempt + 1) * 8 if is_rate_limit else 2
                        logging.warning("API error (%s). Retrying AI request in %s seconds...", "rate limit" if is_rate_limit else "network error", sleep_time)
                        time.sleep(sleep_time)
                        continue
                # If it's not a rate limit or network error, or we exceeded max attempts, raise it so the fallback mechanism triggers
                raise e

        self._cache[key] = result
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        return result

    def _ask_impl(self, prompt: str, img_path: Optional[str], system_override: Optional[str], use_chat: bool, use_rag: bool, max_tokens: Optional[int] = None, history=None) -> str:
        """Core ask logic (caching is handled by ask())."""
        sys_p = system_override or self.system_prompt

        if use_rag and self.context_compiler and self.vector_store and getattr(self.vector_store, "rag_available", True):
            try:
                episodes = self.vector_store.search_episodes(prompt, limit=5)
                historical_data = "\n".join([str(e) for e in episodes]) if episodes else ""
                if hasattr(self, 'memory_manager') and self.memory_manager:
                    try:
                        mm_hits = self.memory_manager.search(prompt, limit=5)
                        if mm_hits:
                            mm_text = "\n".join([f"{h.key}: {h.value}" for h in mm_hits])
                            historical_data = f"{historical_data}\n{mm_text}" if historical_data else mm_text
                        # NOTE: expired-memory cleanup runs on the maintenance
                        # thread (see ensure_maintenance_thread), never here.
                    except Exception as _e:
                        logging.debug("[core/brain.py:203] Swallowed exception: %s: %s", type(_e).__name__, _e)
                sys_p = self.context_compiler.compile(sys_p, {"memory": historical_data})
            except Exception as e:
                logging.debug("[core/brain.py:206] Swallowed exception: %s: %s", type(e).__name__, e)
                print(f"[Context Compilation Warning]: {e}")

        online = is_online()
        if online:
            active = getattr(Config, 'ACTIVE_PROVIDER', 'auto').lower() if hasattr(Config, 'ACTIVE_PROVIDER') else 'auto'
            if active in ('auto','groq') and self.groq_client:
                try:
                    model = getattr(self, 'groq_model', getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b'))
                    kwargs = dict(messages=self._build_messages(sys_p, prompt, history), model=model, timeout=Config.LLM_REQUEST_TIMEOUT)
                    if max_tokens is not None:
                        kwargs["max_tokens"] = max_tokens
                    chat_completion = self.groq_client.chat.completions.create(**kwargs)
                    return chat_completion.choices[0].message.content
                except Exception as e:
                    err_str = str(e).lower()
                    is_retryable = "429" in err_str or "rate limit" in err_str or "too many requests" in err_str or "broken pipe" in err_str or "connection" in err_str or "timeout" in err_str
                    if active != 'auto' and is_retryable:
                        raise e
                    logging.debug("[core/brain.py:228] Swallowed exception: %s: %s", type(e).__name__, e)
                    print(f"[Groq Error]: {e} - Falling back")
                    if active == 'groq':
                        # Tool-call error: model generated a tool call despite tool_choice=none.
                        # Try other providers before falling back to DDG.
                        is_tool_err = "tool choice" in err_str or "tool_use_failed" in err_str or "tool_use" in err_str
                        if is_tool_err:
                            r = self._ask_openai_compatible(self.openai_client, getattr(Config, 'OPENAI_MODEL', 'gpt-4o-mini'), prompt, sys_p, max_tokens, history)
                            if r: return r
                            r = self._ask_openai_compatible(self.deepseek_client, getattr(Config, 'DEEPSEEK_MODEL', 'deepseek-chat'), prompt, sys_p, max_tokens, history)
                            if r: return r
                        return self._ddg_search(prompt) if online else ""
            if active in ('auto','openai'):
                r = self._ask_openai_compatible(self.openai_client, getattr(Config, 'OPENAI_MODEL', 'gpt-4o-mini'), prompt, sys_p, max_tokens, history)
                if r: return r
            if active in ('auto','deepseek'):
                r = self._ask_openai_compatible(self.deepseek_client, getattr(Config, 'DEEPSEEK_MODEL', 'deepseek-chat'), prompt, sys_p, max_tokens, history)
                if r: return r
            if active in ('auto','mistral'):
                r = self._ask_openai_compatible(self.mistral_client, getattr(Config, 'MISTRAL_MODEL', 'mistral-small-latest'), prompt, sys_p, max_tokens, history)
                if r: return r
            if active in ('auto','gemini'):
                gname = getattr(Config, 'GEMINI_MODEL', getattr(self, 'gemini_model_name', 'gemini-2.0-flash'))
                if getattr(self, 'gemini_new_client', None) is not None:
                    try:
                        history_text = self._history_as_text(history)
                        full_prompt = prompt
                        if sys_p != self.system_prompt:
                            full_prompt = f"{sys_p}\n\nUser: {prompt}"
                        if history_text:
                            full_prompt = f"Recent conversation:\n{history_text}\n\n{full_prompt}"
                        if img_path:
                            resp = self.gemini_new_client.models.generate_content(model=gname, contents=[full_prompt, Image.open(img_path)])
                        else:
                            resp = self.gemini_new_client.models.generate_content(model=gname, contents=full_prompt)
                        if getattr(resp, 'text', None):
                            return resp.text
                    except Exception as e:
                        err_str = str(e).lower()
                        is_retryable = "429" in err_str or "rate limit" in err_str or "too many requests" in err_str or "broken pipe" in err_str or "connection" in err_str or "timeout" in err_str
                        if active != 'auto' and is_retryable:
                            raise e
                        logging.debug("[core/brain.py:246] Swallowed exception: %s: %s", type(e).__name__, e)
                        print(f"[Gemini Error]: {e} - Falling back")
                        if active == 'gemini': return self._ddg_search(prompt) if online else ""
                if getattr(self, 'gemini_model', None) is not None and genai_legacy is not None:
                    try:
                        model = self.gemini_model
                        if sys_p != self.system_prompt:
                            model = genai_legacy.GenerativeModel(gname, system_instruction=sys_p)
                        history_text = self._history_as_text(history)
                        model_prompt = prompt
                        if history_text:
                            model_prompt = f"Recent conversation:\n{history_text}\n\nUser: {prompt}"
                        if img_path:
                            return model.generate_content([model_prompt, Image.open(img_path)]).text
                        if use_chat and self.gemini_chat:
                            return self.gemini_chat.send_message(model_prompt).text
                        return model.generate_content(model_prompt).text
                    except Exception as e:
                        logging.debug("[core/brain.py:256] Swallowed exception: %s: %s", type(e).__name__, e)
                        print(f"[Gemini Error]: {e} - Falling back")
            if active in ('auto','anthropic'):
                r = self._ask_anthropic(prompt, sys_p, history)
                if r: return r
            if self.provider_manager:
                try:
                    resp, pname = self.provider_manager.query(prompt, system_override=sys_p, img_path=img_path, history=history)
                    if resp:
                        return resp
                except Exception as _e:
                    logging.debug("[core/brain.py:268] Swallowed exception: %s: %s", type(_e).__name__, _e)
            # A specific active provider was requested but failed — skip the rest.
            if active != 'auto':
                return self._ddg_search(prompt) if online else ""

        # Local Ollama reasoning (deepseek-r1) — always preferred when available
        try:
            ollama_reason = self._ollama_reasoning(prompt, sys_p, history)
            if ollama_reason:
                return ollama_reason
        except Exception as e:
            logging.debug("[core/brain.py:307] Ollama reasoning swallowed: %s", e)
        ollama_res = self._ask_ollama(prompt)
        if ollama_res:
            return ollama_res
        if online:
            return self._ddg_search(prompt)
        return "All AI providers are unavailable right now — online LLMs and local Ollama both failed. Check your internet connection or start Ollama if you'd like local processing."

    def ask_stream(self, prompt: str, system_override: Optional[str] = None, use_rag: bool = False, max_tokens: Optional[int] = None, history=None):
        """Streaming version - yields text chunks as they arrive (Groq/OpenAI streaming, else fallback)."""
        sys_p = system_override or self.system_prompt
        active = getattr(Config, 'ACTIVE_PROVIDER', 'auto').lower() if hasattr(Config, 'ACTIVE_PROVIDER') else 'auto'
        if is_online():
            if active in ('auto','groq') and self.groq_client:
                try:
                    model = getattr(self, 'groq_model', getattr(Config, 'GROQ_MODEL', 'openai/gpt-oss-20b'))
                    kwargs = dict(messages=self._build_messages(sys_p, prompt, history), model=model, stream=True, timeout=Config.LLM_REQUEST_TIMEOUT)
                    if max_tokens is not None:
                        kwargs["max_tokens"] = max_tokens
                    stream = self.groq_client.chat.completions.create(**kwargs)
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta
                    return
                except Exception as e:
                    logging.debug("[core/brain.py:299] Swallowed exception: %s: %s", type(e).__name__, e)
                    print(f"[Groq Stream Error]: {e}")
            if active in ('auto','openai') and self.openai_client:
                try:
                    model = getattr(Config, 'OPENAI_MODEL', 'gpt-4o-mini')
                    kwargs = dict(messages=self._build_messages(sys_p, prompt, history), model=model, stream=True, timeout=Config.LLM_REQUEST_TIMEOUT)
                    if max_tokens is not None:
                        kwargs["max_tokens"] = max_tokens
                    stream = self.openai_client.chat.completions.create(**kwargs)
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                        if delta:
                            yield delta
                    return
                except Exception as e:
                    logging.debug("[core/brain.py:313] Swallowed exception: %s: %s", type(e).__name__, e)
                    print(f"[OpenAI Stream Error]: {e}")
        if self._ollama_available():
            try:
                for chunk in self._ollama_chat_stream(
                    "deepseek-r1",
                    self._build_messages(sys_p, prompt, history),
                ):
                    yield chunk
                return
            except Exception as e:
                logging.debug("[core/brain.py:350] Ollama stream swallowed: %s", e)
        yield self.ask(prompt, system_override=system_override, use_rag=use_rag, max_tokens=max_tokens, history=history)

    def react(self, prompt: str, tool_registry=None, max_steps: int = 5) -> str:
        """Run a ReAct agent loop — reason, act with tools, observe, reflect."""
        try:
            from core.agent_loop import ReActAgent
            agent = ReActAgent(tool_registry=tool_registry, max_steps=max_steps)
            return agent.run(prompt)
        except Exception as e:
            logging.debug("[core/brain.py:react] Swallowed exception: %s: %s", type(e).__name__, e)
            return f"Agent error: {e}. Falling back to direct response."

    def _ask_ollama(self, prompt: str) -> Optional[str]:
        """Tries to get a response from a local Ollama instance."""
        try:
            payload = {
                "model": Config.OLLAMA_MODEL,
                "prompt": f"{self.system_prompt}\n\nUser: {prompt}\n{Config.NAME}:",
                "stream": False
            }
            # Increased timeout for initial model loading
            response = requests.post(Config.OLLAMA_URL, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json().get("response", "").strip()
            else:
                err_msg = response.json().get("error", "Unknown Ollama Error")
                print(f"[Ollama Error {response.status_code}]: {err_msg}")
        except Exception as e:
            logging.debug("[core/brain.py:332] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[Ollama Connection Error]: {e}")
        return None

    @staticmethod
    def _ollama_base() -> str:
        """Derive the Ollama host (scheme://netloc) from Config.OLLAMA_URL.

        Config.OLLAMA_URL defaults to 'http://localhost:11434/api/generate'
        (the generate endpoint), while tags/chat use '/api/tags' and
        '/api/chat'. Centralising here avoids hardcoded localhost drift.
        """
        try:
            from urllib.parse import urlparse
            raw = getattr(Config, "OLLAMA_URL", "http://localhost:11434/api/generate") or "http://localhost:11434/api/generate"
            parts = urlparse(raw)
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}"
        except Exception as _e:
            logging.debug("[core/brain.py:ollama_base] Swallowed exception: %s: %s", type(_e).__name__, _e)
        return "http://localhost:11434"

    def _ollama_available(self) -> bool:
        """Check if a local Ollama server is running."""
        try:
            req = Request(f"{self._ollama_base()}/api/tags")
            with urlopen(req, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _ollama_chat_stream(self, model: str, messages: list, temperature: float = 0.7):
        """Stream tokens from a local Ollama chat endpoint."""
        try:
            payload = {"model": model, "messages": messages, "stream": True, "options": {"temperature": temperature}}
            req = Request(f"{self._ollama_base()}/api/chat", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=10) as resp:
                for line in resp:
                    line = line.decode().strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("done"):
                        return
                    content = obj.get("message", {}).get("content", "")
                    if content:
                        yield content
        except Exception as e:
            logging.debug("[core/brain.py:ollama_stream] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[Ollama Stream Error]: {e}")

    def _ollama_reasoning(self, prompt: str, system_prompt: str = None, history=None) -> str:
        """Use a local reasoning model (deepseek-r1) for plan/think steps."""
        if not self._ollama_available():
            return None
        model = "deepseek-r1"
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
            with urlopen(req, timeout=60) as resp:
                obj = json.loads(resp.read().decode())
                return obj.get("message", {}).get("content", "")
        except Exception as e:
            logging.debug("[core/brain.py:ollama_reasoning] Swallowed exception: %s: %s", type(e).__name__, e)
            return None

    def _ddg_search(self, prompt: str) -> str:
        """Web-search fallback via ddgs, with timeout and friendly fallback."""
        if DDGS is None:
            return "I've searched for you, Dhanush, but I couldn't find a clear enough summary to read back. I've opened the browser results for you."
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
            logging.debug("[core/brain.py:349] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[Brain Error]: {e}")
        return "I've searched for you, Dhanush, but I couldn't find a clear enough summary to read back. I've opened the browser results for you."

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

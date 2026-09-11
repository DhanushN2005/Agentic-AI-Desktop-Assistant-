import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# Try new google-genai first, fallback to deprecated google-generativeai
try:
    from google import genai as genai_new
    import google.generativeai as genai
    _USE_NEW_GENAI = True
except ImportError:
    try:
        import google.generativeai as genai
        genai_new = None
        _USE_NEW_GENAI = False
    except ImportError:
        genai = None
        genai_new = None
        _USE_NEW_GENAI = False
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")
try:
    from groq import Groq
except ImportError as e:
    print(f"[Groq Import Error]: {e} - Groq API will be disabled.")
    Groq = None
import requests
import json
from PIL import Image
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS
import re
from typing import Optional
from utils.config import Config
from utils.helpers import is_online

class Brain:
    def __init__(self):
        self.gemini_model = None
        self.gemini_chat = None
        self.groq_client = None
        self.openai_client = None
        self.deepseek_client = None
        self.anthropic_client = None
        self.mistral_client = None
        self.system_prompt = Config.SYSTEM_PROMPT_STANDARD
        # Provider manager for fallback + dynamic provider list
        self.provider_manager = None
        try:
            from core.llm_providers import LLMProviderManager
            self.provider_manager = LLMProviderManager()
        except Exception as e:
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
            print(f"[Context Engine Error]: {e} - Proceeding with raw context.")

    def _init_all_providers(self):
        """Initialize all LLM clients from Config (supports hot-reload)."""
        # Groq (model from Config.GROQ_MODEL)
        if Config.GROQ_API_KEY and Groq:
            try:
                self.groq_client = Groq(api_key=Config.GROQ_API_KEY)
                self.groq_model = getattr(Config, 'GROQ_MODEL', 'llama-3.1-8b-instant')
            except Exception as e:
                print(f"[Groq Init Error]: {e}")
                self.groq_client = None
        else:
            self.groq_client = None
            self.groq_model = getattr(Config, 'GROQ_MODEL', 'llama-3.1-8b-instant')
        # Gemini (model from Config.GEMINI_MODEL)
        if Config.GEMINI_API_KEY and genai:
            try:
                gemini_model_name = getattr(Config, 'GEMINI_MODEL', 'gemini-1.5-flash')
                genai.configure(api_key=Config.GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel(gemini_model_name, system_instruction=self.system_prompt)
                self.gemini_chat = self.gemini_model.start_chat()
                self.gemini_model_name = gemini_model_name
            except Exception as e:
                print(f"[Gemini Init Error]: {e}")
                self.gemini_model = None
        else:
            self.gemini_model = None
            self.gemini_chat = None
            self.gemini_model_name = getattr(Config, 'GEMINI_MODEL', 'gemini-1.5-flash')
        # OpenAI + DeepSeek + Mistral (OpenAI-compatible)
        try:
            from openai import OpenAI
            if Config.OPENAI_API_KEY:
                try: self.openai_client = OpenAI(api_key=Config.OPENAI_API_KEY)
                except: self.openai_client = None
            else: self.openai_client = None
            if Config.DEEPSEEK_API_KEY:
                try: self.deepseek_client = OpenAI(api_key=Config.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
                except: self.deepseek_client = None
            else: self.deepseek_client = None
            if Config.MISTRAL_API_KEY:
                try: self.mistral_client = OpenAI(api_key=Config.MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1")
                except: self.mistral_client = None
            else: self.mistral_client = None
        except ImportError:
            self.openai_client = self.deepseek_client = self.mistral_client = None
        # Anthropic
        if Config.ANTHROPIC_API_KEY:
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
            except Exception as e:
                print(f"[Anthropic Init Error]: {e}")
                self.anthropic_client = None
        else:
            self.anthropic_client = None

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
            except: pass
        print("[Brain] Providers reloaded from .env")

    def get_provider_status(self) -> dict:
        """Return status dict for UI badges."""
        from utils.config import Config as C
        return C.get_all_keys_masked()

    def _ask_openai_compatible(self, client, model: str, prompt: str, sys_p: str) -> Optional[str]:
        if not client:
            return None
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": prompt}],
                timeout=20,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[OpenAI-Compatible Error ({model})]: {e}")
            return None

    def _ask_anthropic(self, prompt: str, sys_p: str) -> Optional[str]:
        if not self.anthropic_client:
            return None
        try:
            anthropic_model = getattr(Config, 'ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
            resp = self.anthropic_client.messages.create(
                model=anthropic_model, max_tokens=2048, system=sys_p,
                messages=[{"role": "user", "content": prompt}]
            )
            return "".join([b.text for b in resp.content if hasattr(b, 'text')])
        except Exception as e:
            print(f"[Anthropic Error]: {e}")
            return None

    def ask(self, prompt: str, img_path: Optional[str] = None, system_override: Optional[str] = None, use_chat: bool = False) -> str:
        """
        Query the AI brain.

        Args:
            prompt: The user or system prompt.
            img_path: Optional path to an image (Gemini vision).
            system_override: Override the default system prompt for tool calls.
            use_chat: If True, route through the persistent Gemini chat session
                      for conversational context retention (FIX 7).
                      Defaults to False (stateless) for full backward compatibility.
        """
        # Use provided override or default
        sys_p = system_override or self.system_prompt
        
        # --- PHASE 2: Context Intelligence Injection ---
        if self.context_compiler and self.vector_store:
            try:
                # Retrieve relevant memory chunks - increased to 5 for richer context
                episodes = self.vector_store.search_episodes(prompt, limit=5)
                historical_data = "\n".join([str(e) for e in episodes]) if episodes else ""
                # Also search structured MemoryManager if wired
                if hasattr(self, 'memory_manager') and self.memory_manager:
                    try:
                        mm_hits = self.memory_manager.search(prompt, limit=5)
                        if mm_hits:
                            mm_text = "\n".join([f"{h.key}: {h.value}" for h in mm_hits])
                            historical_data = f"{historical_data}\n{mm_text}" if historical_data else mm_text
                        # Cleanup expired periodically
                        if len(mm_hits) > 0 and hash(prompt) % 20 == 0:
                            self.memory_manager.cleanup_expired()
                    except: pass
                # Compile context
                sys_p = self.context_compiler.compile(sys_p, {"memory": historical_data})
            except Exception as e:
                print(f"[Context Compilation Warning]: {e}")
                
        # 1. Check for Online status
        online = is_online()

        if online:
            # Active provider override
            active = getattr(Config, 'ACTIVE_PROVIDER', 'auto').lower() if hasattr(Config, 'ACTIVE_PROVIDER') else 'auto'
            # Priority chain: Groq -> OpenAI -> DeepSeek -> Gemini -> Anthropic -> Mistral (or single active)
            # Groq
            if active in ('auto','groq') and self.groq_client:
                try:
                    model = getattr(self, 'groq_model', getattr(Config, 'GROQ_MODEL', 'llama-3.1-8b-instant'))
                    chat_completion = self.groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": prompt}
                        ],
                        model=model,
                    )
                    return chat_completion.choices[0].message.content
                except Exception as e:
                    print(f"[Groq Error]: {e} - Falling back")
                    if active == 'groq': return self._ddg_search(prompt) if online else ""
            # OpenAI (GPT)
            if active in ('auto','openai'):
                r = self._ask_openai_compatible(self.openai_client, getattr(Config, 'OPENAI_MODEL', 'gpt-4o-mini'), prompt, sys_p)
                if r: return r
                if active == 'openai' and r is None and self.openai_client: pass
            # DeepSeek
            if active in ('auto','deepseek'):
                r = self._ask_openai_compatible(self.deepseek_client, getattr(Config, 'DEEPSEEK_MODEL', 'deepseek-chat'), prompt, sys_p)
                if r: return r
            # Mistral
            if active in ('auto','mistral'):
                r = self._ask_openai_compatible(self.mistral_client, getattr(Config, 'MISTRAL_MODEL', 'mistral-small-latest'), prompt, sys_p)
                if r: return r
            # Gemini
            if active in ('auto','gemini') and self.gemini_model:
                try:
                    model = self.gemini_model
                    if sys_p != self.system_prompt:
                        gname = getattr(Config, 'GEMINI_MODEL', getattr(self, 'gemini_model_name', 'gemini-1.5-flash'))
                        model = genai.GenerativeModel(gname, system_instruction=sys_p)
                    if img_path:
                        return model.generate_content([prompt, Image.open(img_path)]).text
                    if use_chat and self.gemini_chat:
                        return self.gemini_chat.send_message(prompt).text
                    return model.generate_content(prompt).text
                except Exception as e:
                    print(f"[Gemini Error]: {e} - Falling back")
            # Anthropic Claude
            if active in ('auto','anthropic'):
                r = self._ask_anthropic(prompt, sys_p)
                if r: return r
            # ProviderManager fallback (covers any custom providers in llm_providers.json)
            if self.provider_manager:
                try:
                    resp, pname = self.provider_manager.query(prompt, system_override=sys_p, img_path=img_path)
                    if resp:
                        return resp
                except: pass

        # 2. Offline / Both APIs failed -> Try Ollama
        ollama_res = self._ask_ollama(prompt)
        if ollama_res:
            return ollama_res

        # 3. Last Resort -> Web Search (if online) or Error
        if online:
            return self._ddg_search(prompt)
        
        return "I am currently offline and my local intelligence (Ollama) is not responding. How can I help you with offline system tasks?"

    def ask_stream(self, prompt: str, system_override: Optional[str] = None):
        """Streaming version - yields text chunks as they arrive (Groq/OpenAI streaming, else fallback)."""
        sys_p = system_override or self.system_prompt
        active = getattr(Config, 'ACTIVE_PROVIDER', 'auto').lower() if hasattr(Config, 'ACTIVE_PROVIDER') else 'auto'
        if is_online():
            if active in ('auto','groq') and self.groq_client:
                try:
                    model = getattr(self, 'groq_model', getattr(Config, 'GROQ_MODEL', 'llama-3.1-8b-instant'))
                    stream = self.groq_client.chat.completions.create(
                        messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": prompt}],
                        model=model,
                        stream=True,
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta
                    return
                except Exception as e:
                    print(f"[Groq Stream Error]: {e}")
            if active in ('auto','openai') and self.openai_client:
                try:
                    model = getattr(Config, 'OPENAI_MODEL', 'gpt-4o-mini')
                    stream = self.openai_client.chat.completions.create(
                        messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": prompt}],
                        model=model, stream=True,
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                        if delta:
                            yield delta
                    return
                except Exception as e:
                    print(f"[OpenAI Stream Error]: {e}")
        yield self.ask(prompt, system_override=system_override)

    def _ask_ollama(self, prompt: str) -> Optional[str]:
        """Tries to get a response from a local Ollama instance."""
        try:
            payload = {
                "model": Config.OLLAMA_MODEL,
                "prompt": f"{self.system_prompt}\n\nUser: {prompt}\n{Config.NAME}:",
                "stream": False
            }
            # Increased timeout for initial model loading
            response = requests.post(Config.OLLAMA_URL, json=payload, timeout=30)
            if response.status_code == 200:
                return response.json().get("response", "").strip()
            else:
                err_msg = response.json().get("error", "Unknown Ollama Error")
                print(f"[Ollama Error {response.status_code}]: {err_msg}")
        except Exception as e:
            print(f"[Ollama Connection Error]: {e}")
        return None

    def _ddg_search(self, query: str) -> str:
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=3, safesearch='on'))
                    if results:
                        body = results[0].get("body", "")
                        body = "".join(char for char in body if char.isprintable())
                        body = re.sub(r'http\S+', '', body)
                        if len(body.strip()) > 5:
                            return f"Based on my web search, {body.strip()[:380]}..."
        except Exception as e:
            print(f"[Brain Error]: {e}")
        return "I've searched for you, Dhanush, but I couldn't find a clear enough summary to read back. I've opened the browser results for you."

    def translate(self, text: str, dest_lang: str) -> str:
        # Use AI for translation - much more reliable than googletrans
        return self.ask(f"Translate the following text to {dest_lang}. Only return the translated text: {text}")

    def summarize_error(self, traceback_str: str) -> str:
        try:
            return self.ask(f"Summarize this Python error in one clear, helpful sentence for a developer: {traceback_str}")
        except:
            return f"An internal error occurred: {traceback_str[:100]}..."

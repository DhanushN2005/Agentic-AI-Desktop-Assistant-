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
        self.system_prompt = Config.SYSTEM_PROMPT_STANDARD
        
        # Initialize Groq
        if Config.GROQ_API_KEY:
            try:
                self.groq_client = Groq(api_key=Config.GROQ_API_KEY)
            except Exception as e:
                print(f"[Groq Init Error]: {e}")

        # Initialize Gemini
        if Config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=Config.GEMINI_API_KEY)
                self.gemini_model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=self.system_prompt)
                self.gemini_chat = self.gemini_model.start_chat()
            except Exception as e:
                print(f"[Gemini Init Error]: {e}")
                
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
            # Try Groq first
            if self.groq_client:
                try:
                    chat_completion = self.groq_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": prompt}
                        ],
                        # Valid Groq models: llama-3.1-8b-instant, llama-3.3-70b-versatile
                        model="llama-3.1-8b-instant",
                    )
                    return chat_completion.choices[0].message.content
                except Exception as e:
                    print(f"[Groq Error]: {e} - Falling back to Gemini")

            # Try Gemini second
            if self.gemini_model:
                try:
                    # RE-INIT GEMINI IF SYSTEM PROMPT CHANGED (GEMINI SPECIFIC)
                    model = self.gemini_model
                    if sys_p != self.system_prompt:
                        model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=sys_p)
                    
                    if img_path:
                        return model.generate_content([prompt, Image.open(img_path)]).text
                    
                    # FIX 7: Conversational queries use the persistent chat session for
                    # context retention; tool/routing calls stay stateless to avoid
                    # prompt contamination across different intent types.
                    if use_chat and self.gemini_chat:
                        return self.gemini_chat.send_message(prompt).text
                    
                    # Stateless call — default behaviour, unchanged from original
                    return model.generate_content(prompt).text
                except Exception as e:
                    print(f"[Gemini Error]: {e} - Falling back to Search")

        # 2. Offline / Both APIs failed -> Try Ollama
        ollama_res = self._ask_ollama(prompt)
        if ollama_res:
            return ollama_res

        # 3. Last Resort -> Web Search (if online) or Error
        if online:
            return self._ddg_search(prompt)
        
        return "I am currently offline and my local intelligence (Ollama) is not responding. How can I help you with offline system tasks?"

    def ask_stream(self, prompt: str, system_override: Optional[str] = None):
        """Streaming version - yields text chunks as they arrive (Groq streaming)."""
        sys_p = system_override or self.system_prompt
        if self.groq_client and is_online():
            try:
                stream = self.groq_client.chat.completions.create(
                    messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": prompt}],
                    model="llama-3.1-8b-instant",
                    stream=True,
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception as e:
                print(f"[Groq Stream Error]: {e}")
        # Fallback: yield full response as one chunk
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

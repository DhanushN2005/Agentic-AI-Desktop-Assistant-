import logging
import threading
import time
import socket
import datetime
import os
import sys
import re
import subprocess
import webbrowser
import atexit
import queue
from typing import Dict, Optional, List
import urllib.parse
import json
from core.capability_registry import CapabilityRegistry
from core.task_classifier import TaskClassifier, TaskType, TaskState
from core.workflow_parser import WorkflowParser
from core.workflow_gatekeeper import WorkflowGatekeeper, ClassificationType
from voice.tts_guard import TTSGuard
from verification.strict_validator import StrictValidator
from verification.capability_validator import CapabilityValidator
from core.task_critic import TaskCritic
from core.agent_arbitrator import AgentArbitrator
from core.dag_planner import DAGPlanner, DAGTask
from verification.semantic_validator import SemanticValidator
from core.capability_provider import PluginDiscovery
from core.execution_graph import ExecutionGraph, ExecutionNode
from core.adaptive_router import AdaptiveRouter
from core.action_result import ActionResult
from core.context_memory import ContextMemory
from core.workflow_executor import WorkflowExecutor
from core.handlers import dispatch_intent, handle_context_command
import uuid

MAX_PLANNING_DEPTH = 2

# Try to import winsound for Windows beeps
try:
    import winsound
except ImportError:
    winsound = None

# Engine Imports
from utils.config import Config
from utils.helpers import get_numbers, is_online
from core.brain import Brain
from core.router import IntentRouter
from engines.memory import MemoryEngine
from engines.system import SystemCtrl
from engines.files import FileManager
from engines.automation import GoalExecutor, RuleEngine
from engines.email_engine import EmailEngine
from engines.browser import BrowserEngine
from engines.vision import VisionEngine
from engines.music import MusicEngine
from engines.developer import DeveloperEngine
from engines.knowledge import KnowledgeEngine
from engines.youtube_controller import YouTubeController
from engines.intelligence import IntelligenceEngine
from interface.voice import VoiceInterface

class FlexieOrchestrator:
    def __init__(self):
        import pythoncom
        pythoncom.CoInitialize()
        self._setup_logging()
        self.logger = logging.getLogger("Flexie")

        # Core Components
        self.voice = VoiceInterface()
        self.memory = MemoryEngine()
        self.brain = Brain()
        self.router = IntentRouter()
        self.ctx = ContextMemory(self.memory)
        # Persistent memory (unifies 5 stores)
        try:
            from core.memory_manager import MemoryManager
            self.memory_manager = MemoryManager()
            self.brain.memory_manager = self.memory_manager
            logging.info("MemoryManager wired to orchestrator and brain")
        except Exception as e:
            self.memory_manager = None
            logging.warning(f"MemoryManager not wired: {e}")
        
        # Interruption Support
        self.stop_event = threading.Event()
        
        # New: Command Queue for single-threaded execution (Fixes Playwright thread errors)
        self.cmd_queue = queue.Queue()
        self.is_processing = False
        self.current_mode = "professional" # Default UI mode
        self.auto_save_enabled = False
        # Modular Safety Layers
        self.tts_guard = TTSGuard()
        self.capability_registry = CapabilityRegistry()
        self.execution_graph = ExecutionGraph()
        self.adaptive_router = AdaptiveRouter()
        self.workflow = WorkflowExecutor(self)
        # Hybrid routing + Goal planning (deferred wiring until ToolRegistry is ready)
        self.hybrid_router = None
        self.goal_planner = None
        try:
            from core.hybrid_router import HybridRouter
            self.hybrid_router = HybridRouter(self.router, ctx=self.ctx)
            logging.info("HybridRouter wired")
        except Exception as e:
            logging.warning(f"HybridRouter not wired: {e}")

        # FIX 12: Async speech queue — decouples TTS from the action worker thread
        # so speech never blocks command execution.
        self._speech_queue = queue.Queue()

        # FIX 11: Per-action timeout map. Used by _blocking_execute to enforce
        # action-specific deadlines rather than relying solely on the global watchdog.
        self.ACTION_TIMEOUTS = {
            "app_op": 5, "browser_navigate": 20, "browser_search": 20,
            "browser_control": 15, "browser_extract": 15, "browser_tabs": 10,
            "clipboard": 2, "vision_capture": 5, "vision_analyze": 10,
            "media": 2, "file_save": 10, "file_op": 8, "file_delete": 5,
            "file_rename": 5, "search": 20, "play_youtube": 15,
            "youtube": 15, "conversational": 30, "power": 3,
            "status": 5, "save_active": 3, "auto_save": 3, "default": 15
        }
        
        # Load Plugins
        self.plugin_discovery = PluginDiscovery(self.capability_registry)
        self.plugin_discovery.discover_and_register()
        
        all_intents = self.capability_registry.get_all_atomic_intents().union({item[0] for item in self.router.intents})
        self.task_classifier = TaskClassifier(all_intents)
        self.workflow_gatekeeper = WorkflowGatekeeper()
        self.workflow_parser = WorkflowParser()
        self.validator = StrictValidator()
        self.capability_validator = CapabilityValidator()
        self.task_critic = TaskCritic()
        self.arbitrator = AgentArbitrator()
        # FIX 3: DAG callback is now _blocking_execute (not handle_command).
        # handle_command's thread-safety guard queues and returns immediately, causing
        # DAG nodes to appear complete before the command actually ran.
        # _blocking_execute uses threading.Event — no busy-waiting (FIX 8).
        self.dag_planner = DAGPlanner(self.workflow.blocking_execute)
        self.semantic_validator = SemanticValidator()
        # Automation scheduler
        try:
            from engines.automation import AutomationScheduler
            self.automation = AutomationScheduler(self)
        except:
            self.automation = None
        # Desktop control + Agent executor + Coding tools
        try:
            from core.desktop_control import DesktopControl
            from core.agent_executor import AgentExecutor
            from core.tool_registry import ToolRegistry
            from core.permission_system import PermissionSystem
            from core.coding_tools import register_coding_tools
            self.desktop_control = DesktopControl()
            self.tool_registry = ToolRegistry()
            self.agent_executor = AgentExecutor(self.tool_registry, PermissionSystem(), self.execution_graph, speak_fn=self.speak, orch=self)
            # Register autonomous coding tools (file.read/write/patch, code.search, git, terminal, test, python.exec)
            try:
                n = register_coding_tools(self.tool_registry, self)
                logging.info(f"CodingTools registered: {n} tools")
            except Exception as ce:
                logging.warning(f"CodingTools registration failed: {ce}")
            # Wire GoalPlanner with brain + registry after registry is ready (fixes None brain bug)
            try:
                from core.goal_planner import GoalPlanner
                if self.goal_planner is None:
                    self.goal_planner = GoalPlanner(brain=self.brain, tool_registry=self.tool_registry)
                    logging.info("GoalPlanner wired with brain+tool_registry")
                else:
                    self.goal_planner.brain = self.brain
                    self.goal_planner.tool_registry = self.tool_registry
            except Exception as ge:
                logging.warning(f"GoalPlanner wiring failed: {ge}")
        except Exception as e:
            self.desktop_control = None
            self.agent_executor = None
            logging.warning(f"DesktopControl/AgentExecutor not wired: {e}")
        # Action Engines
        self.files = FileManager()
        self.goals = GoalExecutor(self)
        self.rules = RuleEngine(self)
        self.email = EmailEngine()
        self.browser = BrowserEngine(self)
        self.vision = VisionEngine()
        self.music = MusicEngine()
        self.dev = DeveloperEngine(self)
        self.knowledge = KnowledgeEngine(self)
        self.yt = YouTubeController(self)
        self.intel = IntelligenceEngine(self)

        # New Free Plugins
        from engines.weather import WeatherEngine
        from engines.image_gen import ImageGenEngine
        from engines.news import NewsEngine
        from engines.alarm import AlarmEngine
        from engines.pdf_reader import PDFReaderEngine
        from engines.clipboard_mgr import ClipboardManagerEngine
        from engines.text_summarizer import TextSummarizerEngine
        from engines.self_awareness import SelfAwareness
        from engines.memory_system import MemorySystem
        from engines.wiki import WikiEngine
        from engines.jokes import JokesEngine
        from engines.quotes import QuotesEngine
        from engines.password_gen import PasswordEngine
        from engines.qrcode_gen import QRCodeEngine
        from engines.dictionary import DictionaryEngine
        from engines.facts import FactsEngine
        from engines.pomodoro import PomodoroEngine
        from engines.ip_lookup import IPLookupEngine
        from engines.text_tools import TextToolsEngine
        from engines.hash_encoder import HashEncoderEngine
        from engines.json_formatter import JSONFormatterEngine
        from engines.color_info import ColorInfoEngine
        from engines.lorem import LoremEngine
        from engines.uuid_gen import UUIDEngine
        from engines.tip_calc import TipCalculatorEngine
        from engines.body_metrics import BodyMetricsEngine
        from engines.age_calc import AgeCalculatorEngine
        self.weather = WeatherEngine()
        self.image_gen = ImageGenEngine()
        self.news = NewsEngine()
        self.alarm = AlarmEngine()
        self.pdf_reader = PDFReaderEngine()
        self.clipboard_mgr = ClipboardManagerEngine()
        self.summarizer = TextSummarizerEngine()
        self.awareness = SelfAwareness()
        self.memory_system = MemorySystem()
        self.wiki = WikiEngine()
        self.jokes = JokesEngine()
        self.quotes = QuotesEngine()
        self.password_gen = PasswordEngine()
        self.qrcode_gen = QRCodeEngine()
        self.dictionary = DictionaryEngine()
        self.facts = FactsEngine()
        self.pomodoro = PomodoroEngine()
        self.ip_lookup = IPLookupEngine()
        self.text_tools = TextToolsEngine()
        self.hash_encoder = HashEncoderEngine()
        self.json_formatter = JSONFormatterEngine()
        self.color_info = ColorInfoEngine()
        self.lorem = LoremEngine()
        self.uuid_gen = UUIDEngine()
        self.tip_calc = TipCalculatorEngine()
        self.body_metrics = BodyMetricsEngine()
        self.age_calc = AgeCalculatorEngine()

        # Connect alarm to speak callback
        self.alarm.set_speak_callback(self.speak)

        self.active = False
        self.undo_stack: List[tuple] = []
        self._setup_networking()
        
        # Register cleanup for Playwright and other engines
        atexit.register(self.cleanup)

    def cleanup(self):
        """Universal cleanup on exit."""
        self.logger.info("Flexie orchestrator cleaning up...")
        if hasattr(self, 'yt'): self.yt.cleanup()
        if hasattr(self, 'browser'): self.browser.cleanup()
        if hasattr(self, 'voice'): self.voice.stop_speech = True

    def _setup_logging(self):
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(Config.LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        logging.basicConfig(
            handlers=[handler],
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            force=True
        )

    def _setup_networking(self):
        self._udp_out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._udp_in.bind(('127.0.0.1', Config.UDP_PORT_ASSISTANT))
            self._udp_in.setblocking(False)
        except Exception as e:
            self.logger.error(f"Networking bind error: {e}")

    def send_to_ui(self, tag: str, value: str):
        try:
            msg = f"{tag}:{value}"
            self._udp_out.sendto(msg.encode('utf-8'), ('127.0.0.1', Config.UDP_PORT_UI))
        except: pass

    def speak(self, text: str, silent: bool = False):
        if not text: return
        
        # Length Safety Guard: Prevent hallucination playback of large logs
        if len(text) > 300:
            self.logger.warning(f"[TTS GUARD] Truncating massively long TTS message ({len(text)} chars).")
            text = text[:300] + "... [Text Truncated for Voice Output]"
        
        # Modular TTS Deduplication Layer
        if not self.tts_guard.should_speak(text):
            self.logger.info(f"[TTS GUARD] Dropping repeated message: {text}")
            return
            
        self.send_to_ui("STATE", "SPEAKING")
        self.send_to_ui("SAY", text)
        self.logger.info(f"Speaking: {text}")
        self.memory.add_chat("Flexie", text) # Persistence
        if hasattr(self, 'memory_manager') and self.memory_manager:
            try:
                from core.memory_manager import MemoryCategory
                self.memory_manager.remember(text[:60], text, MemoryCategory.CONVERSATION, importance=0.2)
            except: pass
        if not silent:
            # FIX 12: Non-blocking — dispatch to dedicated speech queue so TTS
            # never blocks the action worker thread.
            self._speech_queue.put(text)

    def speak_stream(self, stream_iter):
        """Consume streaming LLM output and speak sentence-by-sentence without waiting for full response."""
        buf = ""
        full = ""
        for chunk in stream_iter:
            if not chunk: continue
            buf += chunk
            full += chunk
            self.send_to_ui("STREAM", chunk)
            # Sentence boundary
            if any(c in buf for c in [". ", "! ", "? ", "\n"]):
                # Split and queue complete sentences
                parts = re.split(r'(?<=[.!?])\s+', buf)
                for p in parts[:-1]:
                    if p.strip():
                        self.speak(p.strip())
                buf = parts[-1] if parts else ""
        if buf.strip():
            self.speak(buf.strip())
        # Persist full stream
        if full.strip():
            self.memory.add_chat("Flexie", full.strip())
        return full.strip()

    def handle_command(self, cmd: str, is_subcommand=False, silent=False, source: str = "user", depth: int = 0):
        if not cmd: return

        # FIX 4: Normalize internal DAG/planner command format to router-compatible
        # natural language BEFORE routing. e.g. "set_brightness:45" → "set brightness 45".
        # This prevents commands generated by the LLM planner from falling through
        # to the noise filter as unroutable conversational inputs.
        cmd = self._normalize_dag_command(cmd)
        
        # Flexie 3.0 Thread safety guard: Redirect all out-of-thread command calls to the queue
        curr_thread = threading.get_ident()
        if hasattr(self, "_action_thread_id") and curr_thread != self._action_thread_id:
            self.logger.info(f"[THREAD SAFE DELEGATION]: Queueing command '{cmd}' from thread {curr_thread}")
            self.cmd_queue.put(cmd)
            return
        
        # Internal helper to handle conditional feedback
        def feedback(msg, final=False):
            if not silent: 
                self.speak(msg)
            elif final:
                self.speak(msg) # Outcome always shown
            else:
                self.logger.info(f"[HACKER SILENT]: {msg}")

        classification = self.workflow_gatekeeper.classify(cmd)
        
        is_simple, parsed_steps = self.workflow_parser.parse_simple_workflow(cmd)
        
        if not is_subcommand and classification == ClassificationType.DETERMINISTIC and is_simple:
            # Fast-path: Check if all subcommands are already explicit Tier-1 commands
            all_high_confidence = True
            for p in parsed_steps:
                _, conf = self.router.route(p.strip())
                if conf < 0.8:
                    all_high_confidence = False
                    break
                    
            if all_high_confidence:
                self.logger.info("[PLANNER] All subcommands are Tier-1. Bypassing semantic planner for fast execution.")
            elif is_online():
                # Try to route compound command semantically first if online and ambiguous
                try:
                    self.send_to_ui("STATE", "THINKING")
                    context = self.memory.get_context(limit=5)
                    intent, confidence, params = self.router.route_dynamic(cmd, self.brain, context=context)
                    if intent == "complex" and confidence >= 0.5 and "steps" in params and params["steps"]:
                        self.logger.info(f"[PLANNER] Compound command routed semantically. Confidence: {confidence:.2f}")
                        self.execute_workflow(params["steps"])
                        return
                except Exception as e:
                    self.logger.error(f"[PLANNER] Dynamic compound routing failed: {e}. Falling back to flat regex split.")
            
            # Track shared context for the duration of this multi-action execution
            # Track shared context for the duration of this multi-action execution
            self._shared_subcommand_context = {
                "had_open_document": False,
                "document_opened": None,
                "chain_result": None
            }
            for p in parsed_steps:
                p_text = p.strip()
                # Semantic Chaining Transformation:
                # If a previous step opened a document, and the current step asks to "paste contents <query>" or "paste <query>" or "write <query>":
                if self._shared_subcommand_context["had_open_document"] or any(k in p_text for k in ["paste", "write", "insert"]):
                    # If this step contains a search query like "what is ..." or "about ..." or "content of ...":
                    if any(q in p_text for q in ["what is", "who is", "about", "content of", "define"]):
                        query = p_text
                        for q in ["paste contents", "paste", "write", "insert", "add"]:
                            query = query.replace(q, "").strip()
                        self.speak(f"Researching {query} to paste into your document.")
                        raw_content = self.brain.ask(f"Generate a clear, concise summary/answer for: {query}.")
                        content = re.sub(r"```(?:\w+)?\n(.*?)\n```", r"\1", raw_content, flags=re.DOTALL).strip()
                        if "```" in content: content = content.replace("```", "")
                        
                        # Copy content to clipboard and perform physical paste (Ctrl+V) using pyautogui
                        import pyperclip
                        import pyautogui
                        pyperclip.copy(content)
                        time.sleep(0.3)
                        pyautogui.hotkey('ctrl', 'v')
                        self.speak("Pasted research contents successfully.")
                        self._shared_subcommand_context["chain_result"] = content
                        continue
                
                # Run standard subcommand execution
                self.handle_command(p_text, is_subcommand=True, silent=silent)
                
                # Context carry-over tracking: if we just opened a document or notepad, set the state
                if any(k in p_text for k in ["open a document", "open document", "create document", "open notepad"]):
                    self._shared_subcommand_context["had_open_document"] = True
            
            # Clean up context
            self._shared_subcommand_context = None
            return

        cmd = self.ctx.resolve(cmd)

        # Intercept specialized context workflow commands from memory
        if handle_context_command(self, cmd, silent):
            return
        c = cmd.strip().lower()
        c = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", c).strip()
        c = re.sub(r"^[,\.\!\?\s]+", "", c).strip()
        
        # Intercept Register Storage Command
        if any(x in c for x in ["save the response in", "save this in", "store this in", "store response in", "save it in"]):
            match = re.search(r"(?:in|to)\s+(?:my\s+)?(\w+)(?:\s+register)?", c)
            if match:
                reg_name = match.group(1).lower().strip()
                response_text = self.ctx.last_response
                if not response_text:
                    self.speak("I don't have any response in this session to save.")
                else:
                    self.ctx.registers[reg_name] = response_text
                    self.speak(f"Saved the response to your {reg_name} register.")
                return
        
        if any(word in c for word in Config.RESTRICTED_WORDS):
            feedback("Content filtered for safety."); return

        self.memory.add_chat("Dhanush", c) # Context Persistence
        # Persistent structured memory with auto-extract
        if hasattr(self, 'memory_manager') and self.memory_manager:
            try:
                from core.memory_manager import MemoryCategory
                import time
                self.memory_manager.remember(c[:80], c, MemoryCategory.CONVERSATION, importance=0.3, tags=["voice"])
                # Auto-extract preferences/facts: "my X is Y", "I like X", "remember that"
                low = c.lower()
                if any(p in low for p in ["my name is", "i like", "i love", "my favorite", "remember that", "i prefer"]):
                    # Extract key: after "my " or "i like "
                    key = c[:40].strip()
                    expiration = None
                    # Short-term for "remember this" without importance
                    if "remember that" in low:
                        importance = 0.8
                    else:
                        importance = 0.6
                    self.memory_manager.remember(f"fact:{key}", c, MemoryCategory.FACTS if "remember" in low else MemoryCategory.PREFERENCES, importance=importance, tags=["auto"])
                    # Also add to VectorStore for semantic search
                    try:
                        self.brain.vector_store.add_episode(f"fact_{int(time.time())}", c, {"source": "auto-extract"})
                    except: pass
            except: pass
        
        # Check Adaptive Router cache first
        intent = self.adaptive_router.get_cached_route(c)
        if intent:
            confidence = 1.0
        else:
            intent, confidence = self.router.route(c)
        params = {}

        # 1b. CONTEXT OVERRIDE: If YouTube is active, redirect ambiguous commands to YouTube control
        yt_control_kw = ["full screen", "fullscreen", "show", "next", "skip", "previous", "pause", "resume", "stop", "volume", "speed", "captions", "subtitle", "forward", "backward", "rewind"]
        if (self.yt.is_session_active() or self.ctx.active_engine == "youtube") and intent not in ("youtube", "play_youtube", "exit", "power"):
            if any(y in c for y in yt_control_kw):
                intent = "youtube"
                confidence = 0.95
        
        # 2. TIER 2: DYNAMIC ROUTING (Agentic Brain)
        # Invoke AI reasoning for low confidence OR complex multi-step prompts
        # Skip length check if it is already a generated subcommand, or if confidence is extremely high (Tier 1 match)
        
        # HybridRouter escalation: check if command is complex via deterministic patterns
        if hasattr(self, 'hybrid_router') and self.hybrid_router and not is_subcommand and depth < MAX_PLANNING_DEPTH:
            try:
                hr_mode = self.hybrid_router.classify(c)
                if hr_mode == "complex":
                    # Try GoalPlanner decomposition for richer task graph
                    if hasattr(self, 'goal_planner') and self.goal_planner:
                        graph = self.goal_planner.decompose(c)
                        if graph and graph.steps and len(graph.steps) > 1:
                            intent = "complex"
                            params = {"steps": [s.command for s in graph.steps]}
                            self.logger.info(f"[HybridRouter+GoalPlanner] {c} -> {params['steps']}")
            except Exception as e:
                self.logger.warning(f"HybridRouter escalation failed: {e}")

        # Modular Classification: Only GOALS can enter semantic planner
        task_type = self.task_classifier.classify(intent, is_subcommand)
        
        needs_dynamic = confidence < 0.8
        # Hybrid escalation: confidence<0.7 or len>8 -> planner
        if hasattr(self, 'hybrid_router') and self.hybrid_router and not is_subcommand:
            if (confidence < 0.7 or len(c.split()) > 8) and self.hybrid_router.classify(c) == "complex":
                needs_dynamic = True
        # FIX: Never re-plan subcommands — they are already planned steps
        if is_subcommand:
            needs_dynamic = False
        elif len(c.split()) > 7 and confidence < 0.9:
            needs_dynamic = True
            
        # Block planner if it's not a GOAL
        if task_type in [TaskType.ACTION, TaskType.SUBACTION]:
            needs_dynamic = False
            
        # FIX: Block planner if already at max depth
        if depth >= MAX_PLANNING_DEPTH:
            needs_dynamic = False
            self.logger.info(f"[PLANNER] Max planning depth ({MAX_PLANNING_DEPTH}) reached. Executing directly.")
            
        if needs_dynamic:
            self.send_to_ui("STATE", "THINKING")
            # Inject Short-term context for follow-up recognition
            context = self.memory.get_context(limit=5)
            intent, confidence, params = self.router.route_dynamic(c, self.brain, context=context)
            
        # 3. AGENTIC EXECUTION (Complex Multi-step)
        if intent == "complex":
            if is_subcommand or depth >= MAX_PLANNING_DEPTH:
                self.logger.warning(f"[ROUTING] Blocked recursive complex intent (depth={depth}). Forcing fallback.")
                intent, confidence = self.router.route(c)
                if intent == "complex": intent = "conversational"
                params = {}
            else:
                steps = params.get("steps", [])
                self.logger.info(f"[PLAN] {cmd} -> {' | '.join(steps)}")
                self.execute_workflow(steps, depth=depth+1)
                return

        # Atomic Action / Goal Classification Trace
        self.logger.info(f"[{task_type.name}] {cmd} (Intent: {intent})")

        # 4. DATA ENRICHMENT: Use extracted params to refine the command
        if params:
            c = params.get("target") or params.get("query") or c

        self.logger.info(f"[ROUTING] Input: '{c}' | Intent: {intent} | Confidence: {confidence:.2f} | Silent: {silent}")

        # 4b. PRE-EMPTIVE FEEDBACK: Speak immediately for long-running tools
        confirmations = {
            "search": "Looking that up for you.",
            "knowledge_search": "Checking your local files.",
            "vision_analyze": "Analyzing your screen now.",
            "vision_debug": "Looking for the error on your screen.",
            "browser_extract": "Reading the page content.",
            "play_youtube": f"Starting YouTube playback for {c}."
        }
        if intent in confirmations and not silent:
            if intent == "play_youtube" and any(x in c for x in ["next", "skip", "kip", "previous", "back"]):
                pass # Suppress pre-emptive message for playback controls
            else:
                self.speak(confirmations[intent])

        # 5. Noise & Low Confidence Filtering
        if intent == "conversational":
            # Allow short conversational inputs instead of dropping them
            if not c.strip():
                self.logger.info(f"[ORCHESTRATOR] Ignoring completely empty input.")
                return

        if confidence < 0.4 and intent != "conversational":
            self.logger.info(f"[ORCHESTRATOR] Low routing confidence ({confidence:.2f}) for intent '{intent}'. Treating as conversational.")
            intent = "conversational"

        if 0.4 <= confidence < 0.75 and intent != "conversational":
            self.logger.info(f"[ORCHESTRATOR] Moderate routing confidence ({confidence:.2f}) for intent '{intent}'. Prompting for clarification.")
            self.send_to_ui("STATE", "THINKING")
            prompt = (
                f"The user said: '{c}'. We classified this as '{intent}' with moderate confidence {confidence:.2f}.\n"
                f"Formulate a friendly, extremely brief (max 12 words) clarification question asking if they meant this or what exactly they want."
            )
            clarification_q = self.brain.ask(prompt)
            self.speak(clarification_q)
            
            # Listen for user reply
            reply = self.voice.listen(timeout=5)
            if reply and reply != "[error_offline]" and len(reply.strip()) > 1:
                combined_cmd = f"{c} (meaning: {reply})"
                self.logger.info(f"[ORCHESTRATOR] Clarification received: '{reply}'. Re-queueing combined command: '{combined_cmd}'")
                self.cmd_queue.put(combined_cmd)
                return
            else:
                self.speak("Okay, let's cancel that or try again.")
                return

        if dispatch_intent(self, intent, c, silent):
            return
    
    def _parse_tool_call(self, response: str) -> bool:
        """Check if AI provided a JSON tool call and execute silently (hacker mode)."""
        # Improved extraction: Find the first { and matching } or last }
        start = response.find('{')
        end = response.rfind('}')
        
        if start == -1 or end == -1 or end < start:
            return False
            
        json_str = response[start:end+1]
        
        try:
            data = json.loads(json_str)
            tool = data.get("tool", "").lower()
            args = data.get("args", {})
            
            # Use silent=True for all sub-commands in hacker mode
            if tool == "open_app":
                self.handle_command(f"open {args.get('name', '')}", silent=True)
            elif tool == "close_app":
                self.handle_command(f"close {args.get('name', '')}", silent=True)
            elif tool in ["web_search", "search"]:
                self.handle_command(f"search for {args.get('query', '')}", silent=True)
            elif tool == "youtube_control":
                act = args.get("action", "play")
                if act == "play": self.handle_command(f"play {args.get('query', '')} on youtube", silent=True)
                else: self.handle_command(f"youtube {act}", silent=True)
            elif tool == "system_control":
                if "volume" in args:
                    v = args["volume"]
                    if v == "increase": self.handle_command("volume 70", silent=True)
                    elif v == "decrease": self.handle_command("volume 30", silent=True)
                    else: self.handle_command(f"volume {v}", silent=True)
                if "brightness" in args:
                    b = args["brightness"]
                    if b == "increase": SystemCtrl.set_brightness(min(100, SystemCtrl.get_brightness()+20))
                    elif b == "decrease": SystemCtrl.set_brightness(max(0, SystemCtrl.get_brightness()-20))
                    else: SystemCtrl.set_brightness(int(b))
            elif tool == "clipboard_analyze":
                self.handle_command("analyze my clipboard", silent=True)
            elif tool == "screen_analyze":
                self.handle_command("analyze my screen", silent=True)
            else:
                return False
                
            return True
        except Exception as e:
            self.logger.error(f"Tool parse failure: {e}")
            return False

    # -------------------------------------------------------------------------
    # FIX 4: Internal DAG command normalizer
    # -------------------------------------------------------------------------
    def _normalize_dag_command(self, cmd: str) -> str:
        """
        Converts internal DAG/planner command format to router-compatible
        natural language (FIX 4).

        Examples:
            'set_brightness:45'   →  'set brightness 45'
            'close_app:notepad'   →  'close app notepad'
            'search_google:python' →  'search google python'

        Commands without ':' are returned unchanged, so this is a no-op for
        all standard natural-language commands.
        """
        if ":" in cmd:
            parts = cmd.split(":", 1)
            action_part = parts[0].strip().replace("_", " ")
            value_part  = parts[1].strip()
            return f"{action_part} {value_part}".strip()
        return cmd

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Thin delegators to WorkflowExecutor (god-object decomposition)
    # -------------------------------------------------------------------------
    def _blocking_execute(self, cmd: str, timeout: float = None) -> ActionResult:
        """Queues and blocks on a command; delegated to WorkflowExecutor."""
        return self.workflow.blocking_execute(cmd, timeout)

    def _verify_step(self, step: str, pre_state: dict, intent: str, max_retries: int = 2):
        """Delegated to WorkflowExecutor."""
        return self.workflow.verify_step(step, pre_state, intent, max_retries)

    def _log_step_result(self, workflow_id: str, step_num: int, total: int,
                          intent: str, duration: float, verified: bool, retries: int):
        """Delegated to WorkflowExecutor."""
        return self.workflow.log_step_result(workflow_id, step_num, total, intent, duration, verified, retries)

    def execute_workflow(self, steps: List[str], depth: int = 0):
        """Delegated to WorkflowExecutor."""
        return self.workflow.execute(steps, depth)

    def _speech_worker_loop(self):
        """Dedicated TTS thread — fully decoupled from the action worker (FIX 12).

        Reads text from _speech_queue and calls voice.speak() sequentially.
        speak() returns immediately after putting text on this queue so the
        action worker is never blocked waiting for audio to finish.
        """
        while True:
            try:
                text = self._speech_queue.get(timeout=1)
                self.voice.speak(text)
                self._speech_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"[SPEECH WORKER] TTS error: {e}")

    def run(self):
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._network_loop, daemon=True).start()
        threading.Thread(target=self._ad_skip_loop, daemon=True).start() # Dedicated High-Freq loop
        threading.Thread(target=self._action_worker, daemon=True).start() # Single dedicated worker
        threading.Thread(target=self._watchdog_loop, daemon=True).start() # New deadlock watchdog monitor
        threading.Thread(target=self._auto_save_loop, daemon=True).start() # New Auto-Save worker
        threading.Thread(target=self._reminder_loop, daemon=True).start() # Voice reminders worker
        threading.Thread(target=self._intelligence_loop, daemon=True).start() # Proactive Suggestions
        threading.Thread(target=self._speech_worker_loop, daemon=True).start() # FIX 12: Async TTS
        try:
            if self.automation: self.automation.start()
        except: pass
        # Ensure system volume is up for voice
        try: SystemCtrl.set_volume(80)
        except: pass
        
        self.speak("Flexie 2.0 Web Automation systems are live and ready, Dhanush.")
        while True:
            try:
                # Update UI state based on activity
                if self.voice.is_speaking:
                    self.send_to_ui("STATE", "SPEAKING")
                    time.sleep(0.1)
                    continue
                elif self.is_processing:
                    self.send_to_ui("STATE", "PROCESSING")
                elif not self.active:
                    self.send_to_ui("STATE", "SLEEP")
                else:
                    self.send_to_ui("STATE", "LISTENING")
                    print("\r[Listener]: Listening...", end="", flush=True)
                
                text = self.voice.listen()
                if not text: 
                    time.sleep(0.1)
                    continue
                
                print(f"\n[User]: \"{text}\"")
                
                if text == "[error_offline]":
                    self.speak("I'm having trouble connecting to my voice recognition service. Please check your internet connection, or use the text interface.")
                    time.sleep(1) # Breathe
                    continue
                
                # INTERRUPTION CHECK: If processing, look for emergency stop words
                if self.is_processing and any(x in text for x in ["stop", "cancel", "halt", "wait"]):
                    self.stop_event.set()
                    self.speak("Task execution terminated.")
                    continue

                # Process the command
                final_cmd = None
                trigger = next((w for w in Config.WAKE_WORDS if w in text), None)
                
                if trigger:
                    self.active = True
                    self.send_to_ui("STATE", "WAKE")
                    if winsound: winsound.Beep(700, 150)
                    final_cmd = text.split(trigger, 1)[-1].strip()
                    final_cmd = re.sub(r"^[,\.\!\?\s]+", "", final_cmd)
                    
                    if not final_cmd:
                        self.speak("Yes?"); follow = self.voice.listen()
                        if follow: final_cmd = follow
                elif self.active:
                    final_cmd = text

                if final_cmd:
                    print(f"[User]: \"{final_cmd}\"")
                    # Clean feedback before putting in queue (Do not repeat raw command)
                    if not any(x in final_cmd for x in ["search", "what is", "who is", "tell me"]):
                         import random
                         acks = ["Okay.", "Sure.", "On it.", "Working on it.", "Got it."]
                         self.speak(random.choice(acks), silent=False)
                    self.cmd_queue.put(final_cmd)
            except Exception as e: 
                self.logger.error(f"Loop Error: {e}")
                time.sleep(1)

    def _ad_skip_loop(self):
        """High-frequency background monitor specifically for YouTube ads."""
        while True:
            # Flexie 3.0: Youtube Ad Skipper is now executed entirely client-side inside the
            # browser using JS setInterval. This background thread is kept as a lightweight no-op
            # to preserve architecture while eliminating Playwright thread-safety conflicts.
            time.sleep(10)

    def _action_worker(self):
        """Dedicated thread to process commands one by one.

        FIX 3, FIX 8: Supports two item formats on cmd_queue:
          - str:  plain command (existing behaviour, unchanged)
          - tuple(str, threading.Event, list): blocking command placed by
            _blocking_execute. On completion the Event is set and the
            ActionResult is appended to the list — no busy-waiting.
        """
        import pythoncom
        pythoncom.CoInitialize()
        self._action_thread_id = threading.get_ident()
        
        while True:
            try:
                try:
                    item = self.cmd_queue.get(timeout=1)
                except queue.Empty:
                    continue

                # FIX 3: Unpack item — support both plain string and blocking tuple
                if isinstance(item, tuple):
                    cmd, done_event, result_holder = item
                else:
                    cmd, done_event, result_holder = item, None, None
                
                if cmd:
                    self.is_processing = True
                    self.last_command_time = time.time()
                    self.last_command_name = cmd
                    self.stop_event.clear()
                    print(f"\n[Orchestrator]: Processing Command: \"{cmd}\"")
                    try:
                        result = self.handle_command(cmd)
                        # FIX 3: Only report success when the command actually ran.
                        # The controller overlay returns a status string; deferred
                        # (awaiting confirmation) or blocked commands must NOT be
                        # marked as executed for DAG/blocking callers.
                        if result_holder is not None:
                            status = result if isinstance(result, str) else "executed"
                            if status in ("blocked", "awaiting_confirmation", "failed", "delegated"):
                                result_holder.append(ActionResult.fail(message=status, intent=cmd))
                            else:
                                result_holder.append(ActionResult.ok(message="Executed", intent=cmd))
                    except Exception as e:
                        self.logger.error(f"Action Worker Error: {e}")
                        # Signal completion with a failure ActionResult (FIX 3)
                        if result_holder is not None:
                            result_holder.append(ActionResult.fail(message=str(e), intent=cmd))
                    finally:
                        self.is_processing = False
                        self.cmd_queue.task_done()
                        # FIX 8: Signal threading.Event — no busy-waiting on caller side
                        if done_event is not None:
                            done_event.set()
            except Exception as e:
                self.logger.critical(f"Action Worker Loop Crash: {e}")
                time.sleep(1)

    def _watchdog_loop(self):
        """Monitors command execution to prevent deadlocks or hangs."""
        while True:
            try:
                if self.is_processing:
                    elapsed = time.time() - getattr(self, "last_command_time", time.time())
                    if elapsed > 45: # 45 seconds execution watchdog limit
                        cmd = getattr(self, "last_command_name", "Unknown")
                        self.logger.critical(f"[WATCHDOG] Command execution hung detected: '{cmd}' ({elapsed:.1f}s elapsed).")
                        
                        # Emergency audio notification
                        self.speak("System Intervention: Active process hung. Recovering controls.", silent=False)
                        
                        # Safely unblock orchestrator queue
                        self.is_processing = False
                        self.stop_event.set()
                        
                        # Safely recover browser references if browser hung
                        if hasattr(self, 'browser') and self.browser:
                            self.browser.logger.warning("Watchdog: Resetting browser references safely due to execution hang.")
                            self.browser.page = None
                            self.browser.context = None
                            self.browser.browser = None
            except Exception as e:
                self.logger.error(f"Watchdog Loop error: {e}")
            time.sleep(5)

    def _monitor_loop(self):
        """Background loop for system metrics and UI updates."""
        while True:
            try:
                # Get metrics
                cpu_val, ram_val = SystemCtrl.cpu_ram()
                batt = SystemCtrl.battery_status()
                
                # Send to UI in JSON format
                metrics = {
                    "cpu": cpu_val,
                    "ram": ram_val,
                    "batt": batt
                }
                # Run Automation Rules
                self.rules.monitor_and_trigger()
                
                self.send_to_ui("METRICS", json.dumps(metrics))
            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}")
            time.sleep(6) # Optimized: Increased sleep to 6s to reduce idle CPU consumption

    def _network_loop(self):
        """Handle incoming commands from UDP (Legacy/Simple) or WebUI."""
        import select
        while True:
            try:
                # Use select to wait for socket data with timeout to reduce idle CPU cycles
                ready = select.select([self._udp_in], [], [], 2.0)
                if ready[0]:
                    data, _ = self._udp_in.recvfrom(1024)
                    msg = data.decode('utf-8').strip()
                    if not msg: continue
                    
                    if msg == "wake up": 
                        self.active = True; self.speak("Ready.")
                    elif msg == "RELOAD_BRAIN":
                        try:
                            self.brain.reload_providers()
                            self.logger.info("Brain reloaded via UI (RELOAD_BRAIN)")
                            self.send_to_ui("SAY", "✅ Brain reloaded — new AI keys & models are live. Try asking something!")
                            self.speak("AI providers reloaded. New keys and models are now active.")
                        except Exception as e:
                            self.logger.error(f"Brain reload failed: {e}")
                            self.send_to_ui("SAY", f"⚠️ Reload failed: {e}")
                    elif msg.startswith("RELOAD_BRAIN:"):
                        # Direct key/model update: RELOAD_BRAIN:provider:key or RELOAD_BRAIN:model:provider:model
                        try:
                            payload = msg.split(":", 1)[1]
                            if payload.startswith("model:"):
                                _, prov, model = payload.split(":", 2)
                                from utils.config import Config as C
                                C.set_model(prov.strip(), model.strip())
                                self.brain.reload_providers()
                            else:
                                prov, key = payload.split(":", 1)
                                from utils.config import Config as C
                                C.set_api_key(prov.strip(), key.strip())
                                self.brain.reload_providers()
                            self.send_to_ui("SAY", "✅ Updated and reloaded.")
                        except Exception as e:
                            self.logger.error(f"RELOAD_BRAIN payload error: {e}")
                    elif msg.startswith("SET_API_KEY:"):
                        # SET_API_KEY:provider:sk-xxx  (from web UI)
                        try:
                            _, prov, key = msg.split(":", 2)
                            from utils.config import Config as C
                            C.set_api_key(prov.strip(), key.strip())
                            self.brain.reload_providers()
                            self.send_to_ui("SAY", f"✅ {prov} key saved. Brain reloaded.")
                            self.speak(f"{prov} key updated.")
                        except Exception as e:
                            self.logger.error(f"SET_API_KEY error: {e}")
                    elif msg.startswith("SET_MODEL:"):
                        # SET_MODEL:provider:model_name
                        try:
                            _, prov, model = msg.split(":", 2)
                            from utils.config import Config as C
                            C.set_model(prov.strip(), model.strip())
                            self.brain.reload_providers()
                            self.send_to_ui("SAY", f"✅ {prov} model set to {model}.")
                        except Exception as e:
                            self.logger.error(f"SET_MODEL error: {e}")
                    elif msg.startswith("SET_ACTIVE_PROVIDER:"):
                        try:
                            prov = msg.split(":", 1)[1].strip().lower()
                            from utils.config import Config as C
                            C.set_active_provider(prov)
                            self.brain.reload_providers()
                            self.send_to_ui("SAY", f"✅ Active provider: {prov}")
                        except Exception as e:
                            self.logger.error(f"SET_ACTIVE_PROVIDER error: {e}")
                    elif msg.startswith("mode:"): # Old UI format
                        self.current_mode = msg.split(":")[1].lower()
                        self.logger.info(f"Mode switched via UDP: {self.current_mode}")
                    elif msg.startswith("SET_VOLUME:"): # UI Slider
                        try:
                            v = int(msg.split(":")[1])
                            SystemCtrl.set_volume(v)
                        except: pass
                    elif msg in ("STOP", "CANCEL", "stop", "cancel"):
                        self.stop_event.set()
                        self.speak("Task cancelled from UI.")
                    else: 
                        # New UI sends direct commands like "volume 50" or "mode hacker"
                        self.cmd_queue.put(msg)
            except Exception as e:
                time.sleep(0.5)

    def _auto_save_loop(self):
        """Background thread that saves work periodically if enabled."""
        while True:
            try:
                if self.auto_save_enabled:
                    # Only save if we are NOT in the middle of a command
                    if not self.is_processing:
                        SystemCtrl.save_active_file()
                        self.logger.info("Auto-save: Ctrl+S sent to active window.")
            except: pass
            time.sleep(60) # Wait 1 minute

    def _reminder_loop(self):
        """Background thread that fires due voice reminders."""
        while True:
            try:
                if not self.is_processing:
                    for task in self.memory.due_reminders():
                        self.speak(f"Reminder: {task}")
            except Exception:
                pass
            time.sleep(20) # Poll every 20 seconds

    def _intelligence_loop(self):
        """Periodically analyze context to offer proactive suggestions."""
        while True:
            try:
                # Only suggest if the user has been active and we are IDLE
                if self.active and not self.is_processing:
                    suggestion = self.intel.analyze_context()
                    if suggestion:
                        self.speak(f"Quick suggestion: {suggestion}")
            except: pass
            time.sleep(600) # Every 10 minutes to avoid being annoying

    def _get_briefing(self) -> str:
        """Aggregates info for a daily brief."""
        brief = []
        try:
            # 1. System Health
            batt = SystemCtrl.battery_status()
            brief.append(f"System Check: {batt}")
            
            # 2. Weather & News (via Brain/Search)
            if is_online():
                # Use a timeout or short prompt for speed
                weather = self.brain.ask("Brief weather update for current location (10 words max).")
                news = self.brain.ask("Top Indian news headline today (10 words max).")
                if "error" not in weather.lower(): brief.append(f"Weather: {weather}")
                if "error" not in news.lower(): brief.append(f"Top News: {news}")
                
                # 3. Emails
                try:
                    emails = self.email.get_unread_emails(count=1)
                    if emails and "credentials" not in emails[0] and "Could not" not in emails[0]:
                        brief.append(f"Recent Email: {emails[0]}")
                except: pass
            else:
                brief.append("I'm currently offline, so I can't fetch live weather or news.")
        except Exception as e:
            self.logger.error(f"Briefing error: {e}")
            return "I encountered an error while preparing your briefing."
            
        return " ".join(brief)


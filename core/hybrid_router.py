"""
Hybrid Router — smart escalation between deterministic routing and agent planning.

Determines whether a command is:
  1. SIMPLE → fast deterministic routing (<50ms)
  2. COMPLEX → agent planner with tool execution

The existing IntentRouter remains the fast path.
This module wraps it and adds escalation logic.
"""
import logging
import re
from typing import Optional
from core.router import IntentRouter
from core.context_memory import ContextMemory
from core.tool_registry import ToolRegistry, PermissionLevel
from core.permission_system import PermissionSystem


# Commands that are ALWAYS simple (never escalate to planner)
ALWAYS_SIMPLE_INTENTS = {
    "undo", "exit", "social", "voice", "status", "awareness",
    "alarm", "weather", "news", "jokes", "quotes", "facts",
    "dictionary", "wiki", "pomodoro", "ip_lookup", "color_info",
    "lorem", "uuid", "tip_calc", "body_metrics", "age_calc",
    "password", "qr_code", "text_tools", "hash_encoder",
    "json_fmt", "memory_system", "list_reminders",
    "local_code_search", "clipboard_mgr",
    "code_gen", "research", "file_save", "automation",
}

# Patterns that indicate compound/complex tasks requiring the planner
COMPLEX_PATTERNS = [
    r"\b(then|after that|next|and then|finally)\b",
    r"\b(find|search)\b.*\b(and|then)\b.*\b(move|rename|copy|delete|save)\b",
    r"\b(open|launch)\b.*\b(and|then)\b.*\b(type|click|fill|search)\b",
    r"\b(read|summarize)\b.*\b(and|then)\b.*\b(save|create|write)\b",
    r"\b(screenshot|capture)\b.*\b(and|then)\b.*\b(analyze|read|extract)\b",
    r"\b(research|investigate)\b.*\b(and|then)\b.*\b(summarize|save|create)\b",
]

# Patterns that indicate the user wants to CANCEL an ongoing task
CANCEL_PATTERNS = [
    r"\b(stop|cancel|abort|never ?mind|forget it|halt|quit)\b",
    r"\b(stop that|cancel that|abort that|hold on)\b",
]


class HybridRouter:
    """
    Wraps the existing IntentRouter with intelligent escalation.
    
    Simple commands → fast deterministic path (existing system).
    Complex commands → GoalPlanner → ToolRegistry execution.
    """

    def __init__(
        self,
        intent_router: IntentRouter,
        tool_registry: Optional[ToolRegistry] = None,
        permission_system: Optional[PermissionSystem] = None,
        ctx: Optional[ContextMemory] = None,
    ):
        self.router = intent_router
        self.tool_registry = tool_registry
        self.permissions = permission_system or PermissionSystem()
        self.ctx = ctx
        self.logger = logging.getLogger("Flexie.HybridRouter")

        # Compile complex patterns
        self._complex_patterns = [re.compile(p, re.IGNORECASE) for p in COMPLEX_PATTERNS]
        self._cancel_patterns = [re.compile(p, re.IGNORECASE) for p in CANCEL_PATTERNS]

    def classify(self, command: str) -> str:
        """
        Classify a command as 'simple' or 'complex'.
        
        Returns:
            "simple" — use deterministic router
            "complex" — use GoalPlanner + tool execution
            "cancel" — user wants to stop current task
        """
        cmd = command.lower().strip()
        if not cmd:
            return "simple"

        # Check for cancellation
        if any(p.search(cmd) for p in self._cancel_patterns):
            return "cancel"

        # Multi-step indicators - check BEFORE always-simple to allow multi-step even with simple intents
        step_indicators = [" and ", " then ", ", ", "also ", "next ", "after "]
        is_multi = any(ind in cmd for ind in step_indicators)
        if is_multi and len(cmd.split()) > 4:
            # 2-part code/research + save is handled internally, not multi-step
            parts = re.split(r",\s*(?:and\s+|then\s+)?|\s+(?:and|then)\s+", cmd)
            parts = [p.strip() for p in parts if len(p.strip()) > 2]
            if len(parts) == 2:
                is_cr = bool(re.search(r"\b(code|script|program|python|java|research|what\s+is|explain|tell\s+me)\b", parts[0]))
                is_save = bool(re.match(r"^(save|export|write)\b", parts[1]))
                if is_cr and is_save:
                    return "simple"
            # Check complex patterns first
            if any(p.search(cmd) for p in self._complex_patterns):
                return "complex"
            return "complex"

        # Check if the intent is always simple
        intent, confidence = self.router.route(cmd)
        if intent in ALWAYS_SIMPLE_INTENTS:
            return "simple"

        # High-confidence simple commands
        if confidence >= 0.95:
            return "simple"

        # Check for complex patterns
        if any(p.search(cmd) for p in self._complex_patterns):
            return "complex"

        # Long commands tend to be complex
        if len(cmd.split()) > 8:
            return "complex"

        # Commands with pronouns referencing previous context might be complex
        if self.ctx and any(w in cmd.split() for w in ["it", "that", "this", "those"]):
            # If there's context to resolve, it might be a follow-up
            if self.ctx.last_query:
                return "complex"

        return "simple"

    def route(self, command: str) -> tuple[str, float, str]:
        """
        Route a command through the hybrid system.
        
        Returns:
            (intent, confidence, mode) where mode is "simple" or "complex"
        """
        mode = self.classify(command)

        if mode == "cancel":
            return "cancel", 1.0, "cancel"

        if mode == "simple":
            intent, confidence = self.router.route(command.lower().strip())
            return intent, confidence, "simple"

        # Complex — will be handled by agent planner
        return "agent_plan", 0.9, "complex"

    def should_escalate(self, intent: str, confidence: float, command: str) -> bool:
        """
        Determine if a routed intent should be escalated to the agent planner.
        
        This is called AFTER the deterministic router to decide if the
        agent planner should take over for better handling.
        """
        cmd = command.lower().strip()

        # Already identified as complex
        if self.classify(command) == "complex":
            return True

        # Low confidence → might benefit from LLM planning
        if confidence < 0.7:
            return True

        # Intent is something the planner can handle better
        planner_friendly_intents = {
            "search", "file_op", "file_save", "file_rename", "file_delete",
            "browser_control", "browser_navigate", "browser_tabs",
            "dev", "dev_build", "vision_analyze",
        }
        if intent in planner_friendly_intents:
            # But only if the command is compound
            if any(x in cmd for x in [" and ", " then ", ","]):
                return True

        return False

    def get_available_tools(self, intent: str = "") -> list:
        """Get available tools, optionally filtered by intent."""
        if not self.tool_registry:
            return []
        if intent:
            return self.tool_registry.get_tools_for_llm(tag=intent)
        return self.tool_registry.get_tools_for_llm()

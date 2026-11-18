"""
Permission System — centralizes all permission checks for tool execution.

Upgrades the existing DangerGate into a proper permission model with levels:
  READ_ONLY → SAFE_ACTION → USER_CONFIRMATION → SENSITIVE → DANGEROUS

Every action must pass through this system. The LLM cannot bypass it.
"""
import logging
import re
import time
import uuid
from collections.abc import Callable

from core.danger_gate import DangerGate
from core.tool_registry import PermissionLevel


class PermissionSystem:
    """
    Centralized permission controller. Wraps DangerGate with structured
    permission levels that map to tool execution requirements.
    """

    def __init__(self, default_level: PermissionLevel = PermissionLevel.READ_ONLY):
        self.default_level = default_level
        self.current_level = default_level
        self.danger_gate = DangerGate()
        self.logger = logging.getLogger("Flexie.PermissionSystem")
        # Expiry (monotonic) for temporary escalations; None = not escalated.
        self._escalation_expires: float | None = None
        self._pending_approval: dict | None = None
        # Sources of untrusted content (web pages, email, MCP output) seen this user turn.
        # While non-empty, side-effecting SAFE_ACTION tools need explicit approval, so
        # injected instructions in that content cannot silently trigger actions.
        self._untrusted_sources: set[str] = set()
        self._on_approval_callback: Callable[[dict], None] | None = None

        # Patterns that classify actions into permission levels
        self._level_patterns = {
            PermissionLevel.READ_ONLY: [
                r"\b(search|find|lookup|read|get|show|list|count|inspect|what|how|who|where|when)\b",
                r"\b(weather|news|time|date|joke|quote|fact|define|wiki|ip address)\b",
                r"\b(word count|character count|reverse|uppercase|lowercase)\b",
                r"\b(md5|sha|base64|hash|encode|decode)\b",
                r"\b(format json|validate json|color info|lorem ipsum|uuid|tip calculator)\b",
                r"\b(bmi|bmr|age calculator|zodiac|days between)\b",
            ],
            PermissionLevel.SAFE_ACTION: [
                r"\b(open|launch|start|close)\s+(app|application|browser|chrome|firefox|notepad|vs code|spotify|vlc)\b",
                r"\b(volume|brightness|mute|unmute|dim|brighten)\b",
                r"\b(search|google|look up|find)\b",
                r"\b(play|pause|stop|resume|skip|next|previous)\b",
                r"\b(take (a )?screenshot|capture|snapshot)\b",
                r"\b(generate|create|make)\s+(image|qr|password|uuid|lorem)\b",
                r"\b(tell me|how do you|define|wikipedia)\b",
                r"\b(timer|alarm|remind me|set timer|set alarm)\b",
                r"\b(set mode|switch mode|change mode)\b",
            ],
            PermissionLevel.USER_CONFIRMATION: [
                r"\b(move|rename|copy|paste|create|write|save)\s+(file|folder|document)\b",
                r"\b(send|compose|reply|forward)\s+(email|mail|message)\b",
                r"\b(delete|remove|erase)\s+(file|folder|document)\b",
                r"\b(modify|edit|change|update)\s+(code|file|document)\b",
                r"\b(install|uninstall|update)\s+(app|package|dependency)\b",
                r"\b(git\s+(add|commit|push|pull|merge|rebase|reset|stash))\b",
                r"\b(organize|sort|clean|arrange)\s+(desktop|folder|files)\b",
                r"\b(run|execute)\s+(script|code|python|node|npm|pip)\b",
                r"\b(powershell|bash|sh|cmd|python|node|npx|pip)\b",
            ],
            PermissionLevel.SENSITIVE: [
                r"\b(terminate|kill|force stop|end process)\b",
                r"\b(shutdown|shut\s+down|power\s+off|restart|reboot|sleep|hibernate|log off|sign out)\b",
                r"\b(lock screen|lock pc|lock computer)\b",
                r"\b(change settings|modify config|update settings)\b",
                r"\b(enable|disable)\s+(auto save|firewall|antivirus)\b",
            ],
            PermissionLevel.DANGEROUS: [
                r"\b(rm -rf|del /s|wipe|erase all)\b",
                r"\bformat\s+[a-z]:",
                r"\b(delete (account|profile|all|everything|permanent))\b",
                r"\b(purchase|buy|pay|transfer money|send money)\b",
                r"\b(confirm payment|place order|checkout)\b",
                r"\b(drop database|drop table|truncate)\b",
                r"\b(override safety|bypass safety|ignore warning)\b",
            ],
        }

        # Compile patterns
        self._compiled = {}
        for level, patterns in self._level_patterns.items():
            self._compiled[level] = [re.compile(p, re.IGNORECASE) for p in patterns]

    # Browsing/reading tools stay free even when tainted; these are the effectful ones.
    _READ_ONLY_TAGS = frozenset({"web", "search", "extract", "intelligence"})

    def mark_untrusted(self, source: str):
        """Record that untrusted content (web/email/MCP output) entered this turn."""
        if source and source not in self._untrusted_sources:
            self._untrusted_sources.add(source)
            self.logger.info(f"[PERMISSION] Untrusted content from {source}: effectful actions now need approval")

    def clear_taint(self):
        """Call at the start of each new user turn."""
        self._untrusted_sources.clear()

    @property
    def is_tainted(self) -> bool:
        return bool(self._untrusted_sources)

    def classify_action(self, command: str) -> PermissionLevel:
        """
        Classifies a command into a permission level based on pattern matching.
        Returns the HIGHEST matching level (most restrictive).

        Empty/whitespace commands classify as USER_CONFIRMATION (fail closed):
        an empty command must never authorize even read-only tools.
        """
        if not command or not command.strip():
            return PermissionLevel.USER_CONFIRMATION

        from core.plan_text import split_clauses

        # Judge each clause on its own so a harmless question does not inherit the level of a
        # risky-sounding word ("what is a good python tutorial", "how do I remove a stain"),
        # while a compound request is still as strict as its riskiest action.
        highest = PermissionLevel.READ_ONLY
        for clause in split_clauses(command) or [command]:
            if self.danger_gate.is_benign_clause(clause):
                continue
            for level in list(PermissionLevel):
                if level in self._compiled:
                    for pattern in self._compiled[level]:
                        if pattern.search(clause):
                            if level.value > highest.value:
                                highest = level
                            break  # Found match for this level, move to next level

        # Also check the existing danger gate
        if self.danger_gate.detect(command):
            if PermissionLevel.USER_CONFIRMATION.value > highest.value:
                highest = PermissionLevel.USER_CONFIRMATION

        return highest

    def _maybe_expire_escalation(self):
        """Auto-reset an expired escalation back to the default level."""
        if self._escalation_expires is None:
            return
        import time as _time
        if _time.monotonic() >= self._escalation_expires:
            self._escalation_expires = None
            self.current_level = self.default_level
            self.logger.info("[PERMISSION] Escalation expired — reset to "
                             f"{self.default_level.name}")

    def check_permission(
        self,
        tool,
        command_context: str = "",
        current_level: PermissionLevel | None = None,
    ) -> tuple[bool, str, PermissionLevel | None]:
        """
        Check if a tool can be executed given the current permission level.

        Args:
            tool: Either a ToolSpec object or a string (tool name / command text)
            command_context: Additional context for classification
            current_level: Override current permission level

        Returns:
            (allowed: bool, reason: str, required_level: Optional[PermissionLevel])
        """
        self._maybe_expire_escalation()
        effective_level = current_level or self.current_level

        # Resolve the required permission level
        if hasattr(tool, 'permission'):
            # It's a ToolSpec object
            required = tool.permission
        else:
            # It's a string — classify based on command context
            context = command_context or (tool if isinstance(tool, str) else "")
            required = self.classify_action(context)

        # Classify the command context for additional checks
        if command_context:
            context_level = self.classify_action(command_context)
            # Use the more restrictive of tool's default and context-derived level
            required = PermissionLevel(max(required.value, context_level.value))

        # Taint: after untrusted content entered the turn, effectful SAFE_ACTION tools
        # (click/fill/open...) are treated as needing confirmation.
        if (
            self._untrusted_sources
            and required == PermissionLevel.SAFE_ACTION
            and hasattr(tool, "tags")
            and not (set(getattr(tool, "tags", [])) & self._READ_ONLY_TAGS)
        ):
            required = PermissionLevel.USER_CONFIRMATION

        if required.value <= effective_level.value:
            return True, "Allowed", required
        else:
            tool_name = tool.name if hasattr(tool, 'name') else str(tool)
            reason = (
                f"Tool '{tool_name}' requires {required.name} permission, "
                f"but current level is {effective_level.name}"
            )
            return False, reason, required

    def requires_confirmation(self, command: str) -> bool:
        """Check if a command requires user confirmation before execution."""
        level = self.classify_action(command)
        return level.value >= PermissionLevel.USER_CONFIRMATION.value

    def is_confirmation(self, text: str) -> bool:
        """Check if user reply is a confirmation."""
        return self.danger_gate.is_confirmation(text)

    def is_cancellation(self, text: str) -> bool:
        """Check if user reply is a cancellation."""
        return self.danger_gate.is_cancellation(text)

    def escalate(self, level: PermissionLevel, ttl_seconds: float = 300.0):
        """Temporarily escalate permission level (e.g., after user confirmation).

        The escalation auto-resets to the default level after ``ttl_seconds``
        (default 5 min); ``reset()`` clears it immediately. ``ttl_seconds<=0``
        means no expiry (stays until ``reset()``) for legacy callers.
        """
        import time as _time
        old = self.current_level
        self.current_level = level
        self._escalation_expires = (_time.monotonic() + ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
        self.logger.info(f"[PERMISSION] Escalated: {old.name} -> {level.name} (ttl={ttl_seconds}s)")

    def await_approval(
        self,
        action: str,
        description: str,
        level: PermissionLevel,
        voice_confirm: Callable[[str], bool] | None = None,
        wait_seconds: float = 20.0,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """Ask the user to approve ``action`` and block until answered or timed out.

        Voice users are asked directly (the action thread is busy, so a spoken
        "confirm" could not be processed any other way); UI/API approval is polled.
        Returns True only on an explicit approval; otherwise the request is rejected
        (fail closed). The caller should ``consume_approval()`` once the action ran.
        """
        import time as _time
        self.create_approval_request(action, details=description, level=level)
        if callable(voice_confirm):
            try:
                if voice_confirm(f"I need your approval to {description}. Should I go ahead?"):
                    self.approve_request()
            except Exception as e:
                self.logger.debug(f"[PermissionSystem] voice approval failed: {e}")
        deadline = _time.monotonic() + wait_seconds
        while True:
            self._maybe_expire_escalation()
            if self.current_level.value >= level.value:
                return True
            if _time.monotonic() >= deadline or (is_cancelled and is_cancelled()):
                break
            _time.sleep(0.25)
        self.reject_request()
        return False

    def consume_approval(self):
        """End an approval's escalation as soon as the approved action finishes, so a
        single approval cannot silently authorize later, unrelated actions."""
        self.reset()

    def reset(self):
        """Reset to default permission level."""
        self._escalation_expires = None
        self.current_level = self.default_level

    def set_approval_callback(self, callback: Callable[[dict], None]):
        """Register a callback invoked when an action requires approval."""
        self._on_approval_callback = callback

    def create_approval_request(
        self,
        action: str,
        details: str = "",
        level: PermissionLevel = PermissionLevel.USER_CONFIRMATION,
    ) -> dict:
        """Create a pending approval request for an action requiring confirmation."""
        req = {
            "id": f"apr_{uuid.uuid4().hex[:8]}",
            "action": action,
            "details": details,
            "level": level,
            "created_at": time.time(),
            "status": "pending",
        }
        self._pending_approval = req
        if self._on_approval_callback:
            try:
                self._on_approval_callback(req)
            except Exception as e:
                self.logger.debug(f"[PermissionSystem] approval callback failed: {e}")
        return req

    def get_pending_request(self) -> dict | None:
        """Return the current pending approval request, if any."""
        return self._pending_approval

    def approve_request(self, request_id: str | None = None, ttl_seconds: float = 60.0) -> bool:
        """Approve the pending request and escalate permission."""
        if not self._pending_approval:
            return False
        if request_id and self._pending_approval.get("id") != request_id:
            return False
        req = self._pending_approval
        req["status"] = "approved"
        level = req.get("level", PermissionLevel.USER_CONFIRMATION)
        self.escalate(level, ttl_seconds=ttl_seconds)
        self._pending_approval = None
        return True

    def reject_request(self, request_id: str | None = None) -> bool:
        """Reject and clear the pending approval request."""
        if not self._pending_approval:
            return False
        if request_id and self._pending_approval.get("id") != request_id:
            return False
        self._pending_approval["status"] = "rejected"
        self._pending_approval = None
        return True

    def to_summary(self) -> str:
        """Human-readable permission summary."""
        return (
            f"Permission System:\n"
            f"  Current Level: {self.current_level.name}\n"
            f"  Default Level: {self.default_level.name}\n"
            f"  Levels: READ_ONLY(1) → SAFE_ACTION(2) → USER_CONFIRMATION(3) → SENSITIVE(4) → DANGEROUS(5)"
        )

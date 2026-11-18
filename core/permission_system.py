"""
Permission System — centralizes all permission checks for tool execution.

Upgrades the existing DangerGate into a proper permission model with levels:
  READ_ONLY → SAFE_ACTION → USER_CONFIRMATION → SENSITIVE → DANGEROUS

Every action must pass through this system. The LLM cannot bypass it.

Approvals are PER REQUEST, not process-wide:
  * every approval request has an id, a TTL and a status (pending/approved/rejected/expired)
  * approving a request creates a *grant* that is active only in the context (thread) that is
    running the approved action, for a short time, and only up to the requested level
  * a bare "confirm" (no id) only approves when exactly ONE request is pending
  * all state is guarded by a lock
The old process-wide ``escalate()`` still exists for explicit, deliberate use.
"""
import contextlib
import contextvars
import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from core.danger_gate import DangerGate
from core.tool_registry import PermissionLevel

PENDING_TTL_SECONDS = 120.0   # how long an unanswered request stays approvable
GRANT_TTL_SECONDS = 60.0      # how long an approval stays usable after it is given
_MAX_REQUESTS = 100


@dataclass
class ApprovalGrant:
    request_id: str
    level: PermissionLevel
    expires_at: float  # monotonic

    def active(self) -> bool:
        return time.monotonic() < self.expires_at


# The grant that applies to the code currently running (per thread / per context).
_active_grant: contextvars.ContextVar["ApprovalGrant | None"] = contextvars.ContextVar(
    "flexie_active_grant", default=None
)


def _current_command_id() -> str:
    """Id of the user command in flight, used to scope untrusted-content taint per command."""
    try:
        from core.telemetry.usage import current_command

        return current_command() or "_global"
    except Exception:
        return "_global"


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
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        # Expiry (monotonic) for temporary process-wide escalations; None = not escalated.
        self._escalation_expires: float | None = None
        self._requests: OrderedDict[str, dict] = OrderedDict()
        # Untrusted content (web pages, email, MCP output) seen, scoped PER COMMAND: a background
        # job starting mid-turn can neither clear nor inherit the user's taint.
        self._untrusted: dict[str, set[str]] = {}
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
                r"\b(send|compose|reply|forward)\s+(an?\s+)?(email|mail|message|text)\b",
                r"\b(delete|remove|erase)\s+(file|folder|document)\b",
                r"\b(modify|edit|change|update)\s+(code|file|document)\b",
                r"\b(install|uninstall|update)\s+(app|package|dependency)\b",
                r"\b(git\s+(add|commit|push|pull|merge|rebase|reset|stash))\b",
                r"\b(organize|sort|clean|arrange)\s+(desktop|folder|files)\b",
                r"\b(run|execute)\s+(script|code|python|node|npm|pip)\b",
                r"\b(powershell|bash|sh|cmd|python|node|npx|pip)\b",
                # Outbound messaging / publishing — judged per clause, so verbs at the START of a clause
                r"\breply\s+(?:to\s+)?all\b",
                r"\bforward\s+(?:this|it|that|the\s+\w+|everything)\s+to\b",
                r"\bsend\s+(it|this|that|them|everything)\b",
                r"\bsend\s+\w+\s+an?\s+(message|text|email|dm|note)\b",
                r"^\s*(?:please\s+)?(?:email|e-mail|mail|text|message|dm|whatsapp|tweet|post)\s+"
                r"(?!me\b|tools?\b|editor\b|files?\b|box\b|apps?\b|about\b|office\b)\w+",
                r"\b(publish|deploy|release)\b",
                r"\bmerge\s+(to|into)\s+\w+",
                r"\b(uninstall|get\s+rid\s+of|trash|dispose\s+of|clear\s+out|overwrite)\b",
                r"\bmove\s+(all|everything)\b",
                r"\bclean\s*up\s+(my\s+|the\s+)?(desktop|downloads|folder|files|disk)\b",
            ],
            PermissionLevel.SENSITIVE: [
                r"\b(terminate|kill|force\s+stop|end)\s+(the\s+|that\s+|this\s+)?(process|task|app|application|program|\w+\.exe)\b",
                r"\b(shutdown|shut\s+down|power\s+off|reboot)\b",
                r"\brestart\s+(the\s+|my\s+)?(pc|computer|laptop|machine|system|windows)\b",
                r"\b(put|send|let)\s+(the\s+|my\s+)?(pc|computer|laptop|machine)\s+(to\s+)?sleep\b|\bhibernate\b",
                r"\b(log\s*off|sign\s*out)\b",
                r"\b(lock screen|lock pc|lock computer)\b",
                r"\b(change settings|modify config|update settings)\b",
                r"\b(enable|disable|turn\s+off|turn\s+on|switch\s+off)\s+(the\s+)?"
                r"(auto\s*save|firewall|antivirus|defender|windows\s+defender|uac|security)\b",
            ],
            PermissionLevel.DANGEROUS: [
                r"\b(rm -rf|del /s|wipe|erase all|nuke|shred|factory\s+reset)\b",
                r"\bformat\s+(the\s+|my\s+)?(drive|disk|partition|usb|[a-z]:)",
                r"\b(delete (account|profile|all|everything|permanent))\b",
                r"\b(purchase|buy|pay(?!\s+(attention|heed|respect|a\s+visit))|transfer\s+(money|funds)|send\s+(money|\$))\b",
                r"\bwire\s+(\$|\d)|\b(venmo|donate|withdraw|paypal)\b|\bsend\s+\$",
                r"\border\s+(a|an|some|me|\d+)\b|^\s*(?:please\s+)?order\s+(?!by\b|of\b|to\b)\w+"
                r"|\bbook\s+(a|an|the)?\s*(flight|hotel|ticket|cab|table|room)\b",
                r"\b(confirm payment|place order|proceed to checkout|checkout\s+(my|the)\s+(cart|basket|order))\b",
                r"\b(drop|truncate)\s+(database|table)\b|\bdelete\s+from\b",
                r"\bgit\s+push\b.*(--force|\s-f\b)",
                r"\b(override safety|bypass safety|ignore warning)\b",
            ],
        }

        # Compile patterns
        self._compiled = {}
        for level, patterns in self._level_patterns.items():
            self._compiled[level] = [re.compile(p, re.IGNORECASE) for p in patterns]

    # ------------------------------------------------------------------ untrusted taint
    # Browsing/reading tools stay free even when tainted; these are the effectful ones.
    _READ_ONLY_TAGS = frozenset({"web", "search", "extract", "intelligence"})

    def mark_untrusted(self, source: str):
        """Record that untrusted content (web/email/MCP output) entered THIS command."""
        if not source:
            return
        key = _current_command_id()
        with self._lock:
            bucket = self._untrusted.setdefault(key, set())
            if source not in bucket:
                bucket.add(source)
                self.logger.info(f"[PERMISSION] Untrusted content from {source}: effectful actions now need approval")
            while len(self._untrusted) > 64:  # bounded: forget the oldest commands
                self._untrusted.pop(next(iter(self._untrusted)))

    def clear_taint(self):
        """Call at the start of a new user turn (clears THIS command's taint)."""
        with self._lock:
            self._untrusted.pop(_current_command_id(), None)

    @property
    def is_tainted(self) -> bool:
        with self._lock:
            return bool(self._untrusted.get(_current_command_id()))

    # -------------------------------------------------------------------- classification
    def classify_action(self, command: str) -> PermissionLevel:
        """
        Classifies a command into a permission level based on pattern matching.
        Returns the HIGHEST matching level (most restrictive).

        Empty/whitespace commands classify as USER_CONFIRMATION (fail closed):
        an empty command must never authorize even read-only tools.
        """
        if not command or not command.strip():
            return PermissionLevel.USER_CONFIRMATION

        highest = PermissionLevel.READ_ONLY
        for clause in self.danger_gate.clauses(command):
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
        if time.monotonic() >= self._escalation_expires:
            with self._lock:
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
        grant = _active_grant.get()
        if grant is not None and grant.active() and grant.level.value > effective_level.value:
            effective_level = grant.level  # an approval for THIS running action

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

        # Taint: after untrusted content entered THIS command, effectful SAFE_ACTION tools
        # (click/fill/open...) are treated as needing confirmation.
        if (
            required == PermissionLevel.SAFE_ACTION
            and hasattr(tool, "tags")
            and self.is_tainted
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

    # ----------------------------------------------------------- explicit escalation
    def escalate(self, level: PermissionLevel, ttl_seconds: float = 300.0):
        """Temporarily escalate the PROCESS-WIDE permission level (deliberate, explicit use).

        Prefer approval requests: they produce a grant that applies only to the approved action.
        The escalation auto-resets after ``ttl_seconds``; ``reset()`` clears it immediately.
        ``ttl_seconds<=0`` means no expiry (stays until ``reset()``) for legacy callers.
        """
        with self._lock:
            old = self.current_level
            self.current_level = level
            self._escalation_expires = (time.monotonic() + ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
        self.logger.info(f"[PERMISSION] Escalated: {old.name} -> {level.name} (ttl={ttl_seconds}s)")

    def consume_approval(self):
        """End the approval that was just used: drop this context's grant (and any explicit
        escalation) so one approval cannot authorize later, unrelated actions."""
        _active_grant.set(None)
        self.reset()

    def reset(self):
        """Reset to default permission level."""
        with self._lock:
            self._escalation_expires = None
            self.current_level = self.default_level

    # ------------------------------------------------------------------- approval requests
    def set_approval_callback(self, callback: Callable[[dict], None]):
        """Register a callback invoked when an action requires approval."""
        self._on_approval_callback = callback

    def _expire_requests(self) -> None:
        now = time.time()
        for req in list(self._requests.values()):
            if req["status"] == "pending" and now >= req["expires_at"]:
                req["status"] = "expired"
        while len(self._requests) > _MAX_REQUESTS:
            self._requests.popitem(last=False)

    def create_approval_request(
        self,
        action: str,
        details: str = "",
        level: PermissionLevel = PermissionLevel.USER_CONFIRMATION,
        ttl_seconds: float = PENDING_TTL_SECONDS,
    ) -> dict:
        """Create a pending approval request for an action requiring confirmation."""
        req = {
            "id": f"apr_{uuid.uuid4().hex[:8]}",
            "action": action,
            "details": details,
            "level": level,
            "created_at": time.time(),
            "expires_at": time.time() + ttl_seconds,
            "status": "pending",
        }
        with self._lock:
            self._expire_requests()
            self._requests[req["id"]] = req
        if self._on_approval_callback:
            try:
                self._on_approval_callback(req)
            except Exception as e:
                self.logger.debug(f"[PermissionSystem] approval callback failed: {e}")
        return req

    def _pending(self) -> list[dict]:
        self._expire_requests()
        return [r for r in self._requests.values() if r["status"] == "pending"]

    def get_pending_request(self) -> dict | None:
        """Return the most recent pending, unexpired approval request, if any."""
        with self._lock:
            pending = self._pending()
            return pending[-1] if pending else None

    @property
    def _pending_approval(self) -> dict | None:  # backward-compatible read access
        return self.get_pending_request()

    def request_status(self, request_id: str) -> str | None:
        with self._lock:
            self._expire_requests()
            req = self._requests.get(request_id)
            return req["status"] if req else None

    def approve_request(self, request_id: str | None = None, ttl_seconds: float = GRANT_TTL_SECONDS) -> bool:
        """Approve a pending request.

        With an id: approves exactly that request. Without an id ("confirm" said out loud):
        approves only when exactly ONE request is pending — with several it refuses, so a
        confirmation can never land on a request the user was not asked about.
        The approval is a grant bound to the request's level and TTL; it does NOT raise the
        process-wide permission level.
        """
        with self._lock:
            pending = self._pending()
            if request_id:
                req = self._requests.get(request_id)
                if req is None or req["status"] != "pending":
                    return False
            else:
                if len(pending) != 1:
                    if len(pending) > 1:
                        self.logger.warning("[PERMISSION] Ambiguous approval: %d requests pending; "
                                            "an explicit request id is required.", len(pending))
                    return False
                req = pending[0]
            req["status"] = "approved"
            req["approved_at"] = time.time()
            req["grant"] = ApprovalGrant(
                request_id=req["id"],
                level=req.get("level", PermissionLevel.USER_CONFIRMATION),
                expires_at=time.monotonic() + ttl_seconds,
            )
            self._cond.notify_all()
        return True

    def reject_request(self, request_id: str | None = None) -> bool:
        """Reject a pending request (all pending requests when no id is given — cancelling is
        always safe)."""
        with self._lock:
            if request_id:
                req = self._requests.get(request_id)
                targets = [req] if req and req["status"] == "pending" else []
            else:
                targets = self._pending()
            for req in targets:
                req["status"] = "rejected"
            if targets:
                self._cond.notify_all()
            return bool(targets)

    # ------------------------------------------------------------------- grant activation
    def _grant_for(self, request_id: str) -> "ApprovalGrant | None":
        with self._lock:
            req = self._requests.get(request_id)
            grant = req.get("grant") if req and req["status"] == "approved" else None
        return grant if grant is not None and grant.active() else None

    @contextlib.contextmanager
    def grant_scope(self, request_id: str | None):
        """Run a block under the grant of an APPROVED request (no-op for unknown/unapproved ids)."""
        grant = self._grant_for(request_id) if request_id else None
        token = _active_grant.set(grant) if grant else None
        try:
            yield grant is not None
        finally:
            if token is not None:
                _active_grant.reset(token)

    def grant_covers(self, level: PermissionLevel) -> bool:
        """True when an approval granted to the CURRENT running action already covers ``level``."""
        grant = _active_grant.get()
        return bool(grant is not None and grant.active() and grant.level.value >= level.value)

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
        "confirm" could not be processed any other way); UI/API approval is awaited.
        Returns True only when THIS request was explicitly approved; otherwise it is rejected
        (fail closed). On approval the grant is activated for the calling thread; the caller
        ends it with ``consume_approval()`` once the approved action has run.
        """
        req = self.create_approval_request(action, details=description, level=level)
        rid = req["id"]
        if callable(voice_confirm):
            try:
                if voice_confirm(f"I need your approval to {description}. Should I go ahead?"):
                    self.approve_request(rid)
            except Exception as e:
                self.logger.debug(f"[PermissionSystem] voice approval failed: {e}")
        deadline = time.monotonic() + wait_seconds
        with self._cond:
            while True:
                self._expire_requests()
                status = self._requests[rid]["status"] if rid in self._requests else "expired"
                if status == "approved":
                    break
                if status in ("rejected", "expired"):
                    return False
                if time.monotonic() >= deadline or (is_cancelled and is_cancelled()):
                    self._requests[rid]["status"] = "rejected"
                    return False
                self._cond.wait(timeout=0.25)
        grant = self._grant_for(rid)
        if grant is None:
            return False
        _active_grant.set(grant)
        return True

    def to_summary(self) -> str:
        """Human-readable permission summary."""
        return (
            f"Permission System:\n"
            f"  Current Level: {self.current_level.name}\n"
            f"  Default Level: {self.default_level.name}\n"
            f"  Levels: READ_ONLY(1) → SAFE_ACTION(2) → USER_CONFIRMATION(3) → SENSITIVE(4) → DANGEROUS(5)"
        )

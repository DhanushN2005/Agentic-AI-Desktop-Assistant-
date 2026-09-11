"""
Permission System — centralizes all permission checks for tool execution.

Upgrades the existing DangerGate into a proper permission model with levels:
  READ_ONLY → SAFE_ACTION → USER_CONFIRMATION → SENSITIVE → DANGEROUS

Every action must pass through this system. The LLM cannot bypass it.
"""
import re
import logging
from typing import Optional
from core.tool_registry import PermissionLevel, ToolSpec
from core.danger_gate import DangerGate


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
            ],
            PermissionLevel.SENSITIVE: [
                r"\b(terminate|kill|force stop|end process)\b",
                r"\b(shutdown|restart|sleep|hibernate|log off|sign out)\b",
                r"\b(lock screen|lock pc|lock computer)\b",
                r"\b(change settings|modify config|update settings)\b",
                r"\b(enable|disable)\s+(auto save|firewall|antivirus)\b",
            ],
            PermissionLevel.DANGEROUS: [
                r"\b(rm -rf|del /s|format c:|wipe|erase all)\b",
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

    def classify_action(self, command: str) -> PermissionLevel:
        """
        Classifies a command into a permission level based on pattern matching.
        Returns the HIGHEST matching level (most restrictive).
        """
        if not command:
            return PermissionLevel.READ_ONLY

        # Check from least restrictive to most restrictive
        # Track the highest matching level
        highest = PermissionLevel.READ_ONLY
        for level in list(PermissionLevel):
            if level in self._compiled:
                for pattern in self._compiled[level]:
                    if pattern.search(command):
                        if level.value > highest.value:
                            highest = level
                        break  # Found match for this level, move to next level

        # Also check the existing danger gate
        if self.danger_gate.detect(command):
            if PermissionLevel.USER_CONFIRMATION.value > highest.value:
                highest = PermissionLevel.USER_CONFIRMATION

        return highest

    def check_permission(
        self,
        tool,
        command_context: str = "",
        current_level: Optional[PermissionLevel] = None,
    ) -> tuple[bool, str, Optional[PermissionLevel]]:
        """
        Check if a tool can be executed given the current permission level.
        
        Args:
            tool: Either a ToolSpec object or a string (tool name / command text)
            command_context: Additional context for classification
            current_level: Override current permission level
        
        Returns:
            (allowed: bool, reason: str, required_level: Optional[PermissionLevel])
        """
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

    def escalate(self, level: PermissionLevel):
        """Temporarily escalate permission level (e.g., after user confirmation)."""
        old = self.current_level
        self.current_level = level
        self.logger.info(f"[PERMISSION] Escalated: {old.name} -> {level.name}")

    def reset(self):
        """Reset to default permission level."""
        self.current_level = self.default_level

    def to_summary(self) -> str:
        """Human-readable permission summary."""
        return (
            f"Permission System:\n"
            f"  Current Level: {self.current_level.name}\n"
            f"  Default Level: {self.default_level.name}\n"
            f"  Levels: READ_ONLY(1) → SAFE_ACTION(2) → USER_CONFIRMATION(3) → SENSITIVE(4) → DANGEROUS(5)"
        )

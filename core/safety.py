import re

from utils.config import Config


class SafetyGuard:
    """Pre-execution safety layer to validate incoming commands."""
    def __init__(self):
        # Additional production-grade restricted patterns
        self.blacklist = [
            # Disk / filesystem destruction
            r"rm -rf", r"rm -fr", r"del /s", r"del /q", r"rd /s", r"rmdir /s",
            r"format c:", r"format /y", r"mkfs", r"dd if=/dev/zero",
            # Privilege escalation & DB destruction
            r"sudo ", r"grant all", r"drop table", r"drop database",
            # PowerShell / shell remote execution
            r"remove-item", r"del -recurse", r"invoke-expression", r"iex\s+",
            r"powershell -enc", r"pwsh -enc", r"start-process", r"reg delete",
            # Force-kill everything variants
            r"taskkill /f", r"kill -9", r"shutdown /s /f", r"shutdown /r /f",
        ]

    def validate(self, command: str) -> bool:
        """Returns True if command is safe to pass to the core engines."""
        cmd = command.lower().strip()

        # 1. System Destruction Patterns
        for pattern in self.blacklist:
            if re.search(pattern, cmd):
                return False

        # 2. Config-based filtering (Backward compatible)
        for word in Config.RESTRICTED_WORDS:
            if word in cmd:
                return False

        # 3. Command Injection Prevention
        # Reject suspicious shell command concatenation characters if not part of a URL
        suspicious_chars = [";", "&&", "||", "`", "$("]
        for char in suspicious_chars:
            if char in cmd:
                if not ("http" in cmd and (char == ";" or char == "&&")):
                    return False

        return True

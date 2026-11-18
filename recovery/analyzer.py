import json
import logging
import re
import threading

from core.brain import Brain
from core.event_bus.bus import Event, EventBus

_CATEGORIES = {"network", "locator", "permission", "syntax", "unknown"}
_singleton: "RecoveryAnalyzer | None" = None
_singleton_lock = threading.Lock()


def get_analyzer(brain: Brain = None) -> "RecoveryAnalyzer":
    """One shared analyzer (one bus subscription) instead of a new one per failed step."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = RecoveryAnalyzer(brain)
        return _singleton


def _validate(diag) -> dict:
    """Coerce a model reply into the documented shape; never trust its types."""
    if not isinstance(diag, dict):
        raise ValueError("diagnosis is not a JSON object")
    cat = str(diag.get("category", "unknown")).lower()
    retry = diag.get("suggested_retry_cmd")
    return {
        "category": cat if cat in _CATEGORIES else "unknown",
        "root_cause": str(diag.get("root_cause", ""))[:300],
        "mitigation": str(diag.get("mitigation", ""))[:300],
        "suggested_retry_cmd": retry if isinstance(retry, str) and retry.strip() else None,
    }


class RecoveryAnalyzer:
    """Recovery agent analyzing execution exceptions to compile root-cause mitigations and retries."""
    def __init__(self, brain: Brain = None):
        self.brain = brain or Brain()
        self.bus = EventBus()
        self.logger = logging.getLogger("RecoveryAnalyzer")
        self.bus.subscribe("telemetry.trace.end", self._on_telemetry_event)

    def _on_telemetry_event(self, event: Event):
        status = event.payload.get("status")
        if status == "failed":
            cmd = event.payload.get("cmd")
            error = event.payload.get("error", "Unknown error")
            self.logger.info(f"RecoveryAnalyzer: Detected failed trace for '{cmd}'. Triggering diagnosis...")

            # Run asynchronous diagnosis
            diagnosis = self.diagnose_failure(cmd, error)
            self.bus.publish(Event("recovery.diagnosis", {
                "command": cmd,
                "error": error,
                "diagnosis": diagnosis
            }))

    def diagnose_failure(self, cmd: str, error_msg: str) -> dict:
        """Classifies failures and compiles adaptive retry/mitigation suggestions."""
        self.logger.info(f"Diagnosing execution failure for: '{cmd}' | Error: '{error_msg}'")

        prompt = f"""
        Analyze the following execution failure for a desktop AI agent:
        Failed Command: "{cmd}"
        Error Message: "{error_msg}"

        Classify this failure into one of these categories:
        - "network" (offline, API timeout)
        - "locator" (browser element not found, page mismatch)
        - "permission" (disk access block, OS lock)
        - "syntax" (code compile crash)
        - "unknown"

        Formulate a mitigation strategy and a retry command.

        Return a JSON object:
        {{
            "category": "string",
            "root_cause": "short explanation",
            "mitigation": "recommended action to resolve",
            "suggested_retry_cmd": "modified command or command setup step (or null if unrecoverable)"
        }}

        Return ONLY valid JSON.
        """

        try:
            res_raw = self.brain.ask(prompt, system_override="You are a system debugging daemon. Return ONLY JSON.")
            cleaned = res_raw.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1).strip()

            return _validate(json.loads(cleaned))
        except Exception as e:
            self.logger.error(f"Failure diagnosis failed: {e}")
            return {
                "category": "unknown",
                "root_cause": f"Diagnosis failed: {e}",
                "mitigation": "Check logs and run manually.",
                "suggested_retry_cmd": None
            }

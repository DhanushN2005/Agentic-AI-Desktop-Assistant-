import logging
from core.orchestrator import FlexieOrchestrator
from core.event_bus.bus import EventBus, Event

class LegacyOrchestratorAdapter:
    """Standardized adapter wrapping the legacy FlexieOrchestrator runtime operations."""
    def __init__(self, orchestrator: FlexieOrchestrator):
        self.orch = orchestrator
        self.bus = EventBus()
        self.logger = logging.getLogger("OrchestratorAdapter")
        
        # Overlay the speak method to dispatch events to the bus
        self.original_speak = self.orch.speak
        self.orch.speak = self.wrapped_speak

    def wrapped_speak(self, text: str, silent: bool = False):
        self.bus.publish(Event("orchestrator.speak", {"text": text, "silent": silent}))
        self.original_speak(text, silent)

    def execute_command(self, cmd: str, silent: bool = False):
        """Standardized interface to dispatch commands directly to the core orchestrator queues."""
        self.bus.publish(Event("orchestrator.command.received", {"command": cmd, "silent": silent}, priority=1))
        
        # Place in queue to guarantee thread safety
        self.orch.cmd_queue.put(cmd)
        
        self.bus.publish(Event("orchestrator.command.enqueued", {"command": cmd}))

    def get_status(self) -> dict:
        return {
            "current_mode": self.orch.current_mode,
            "auto_save": self.orch.auto_save_enabled,
            "active": self.orch.active,
            "processing": self.orch.is_processing
        }

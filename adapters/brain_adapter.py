import logging
import time
from core.brain import Brain
from core.event_bus.bus import EventBus, Event

class LegacyBrainAdapter:
    """Wraps the legacy Brain module, publishing query traces to the Event Bus."""
    def __init__(self, brain: Brain):
        self.brain = brain
        self.bus = EventBus()
        self.logger = logging.getLogger("BrainAdapter")

    def ask(self, prompt: str, img_path: str = None, system_override: str = None) -> str:
        self.bus.publish(Event("brain.ask.start", {
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "has_image": img_path is not None
        }))
        
        start_time = time.perf_counter() if 'time' in globals() else 0
        try:
            res = self.brain.ask(prompt, img_path, system_override)
            self.bus.publish(Event("brain.ask.success", {"result_len": len(res)}))
            return res
        except Exception as e:
            self.bus.publish(Event("brain.ask.failed", {"error": str(e)}, priority=0))
            raise e

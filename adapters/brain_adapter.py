import logging
import time

from core.brain import Brain
from core.event_bus.bus import Event, EventBus


class LegacyBrainAdapter:
    """Wraps the legacy Brain module, publishing query traces to the Event Bus."""
    def __init__(self, brain: Brain):
        self.brain = brain
        self.bus = EventBus()
        self.logger = logging.getLogger("BrainAdapter")

    def ask(self, prompt: str, img_path: str = None, system_override: str = None, use_rag: bool = True, max_tokens=None, history=None) -> str:
        self.bus.publish(Event("brain.ask.start", {
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "has_image": img_path is not None
        }))

        start_time = time.perf_counter()
        try:
            res = self.brain.ask(
                prompt,
                img_path,
                system_override,
                use_rag=use_rag,
                max_tokens=max_tokens,
                history=history,
            )
            self.bus.publish(Event("brain.ask.success", {
                "result_len": len(res),
                "latency_ms": round((time.perf_counter() - start_time) * 1000, 1),
            }))
            return res
        except Exception as e:
            self.bus.publish(Event("brain.ask.failed", {"error": str(e)}, priority=0))
            raise e

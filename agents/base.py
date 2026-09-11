import logging
import time
from typing import Dict, Any, List
from core.event_bus.bus import EventBus, Event

class BaseAgent:
    """Standard base interface for autonomous agents executing via the async Event Bus."""
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.bus = EventBus()
        self.logger = logging.getLogger(f"Agent.{name}")
        self.processed_events_count = 0
        self.total_execution_time = 0.0

        # Subscribe to standard agent message routing channel
        self.bus.subscribe(f"agent.{self.name}.task", self._on_task_received)
        self.bus.subscribe("agent.broadcast", self._on_broadcast_received)

    def _on_task_received(self, event: Event):
        """Asynchronously triggers task execution when enqueued on the Event Bus."""
        task_id = event.payload.get("task_id")
        prompt = event.payload.get("prompt")
        self.logger.info(f"Agent '{self.name}' received task {task_id}: '{prompt}'")
        
        start_time = time.perf_counter()
        self.processed_events_count += 1
        
        self.bus.publish(Event(f"agent.{self.name}.executing", {"task_id": task_id}))
        
        try:
            result = self.execute_task(event.payload)
            latency = time.perf_counter() - start_time
            self.total_execution_time += latency
            
            # Publish completion event
            self.bus.publish(Event(f"agent.{self.name}.completed", {
                "task_id": task_id,
                "status": "success",
                "result": result,
                "latency_ms": round(latency * 1000, 2)
            }))
        except Exception as e:
            latency = time.perf_counter() - start_time
            self.total_execution_time += latency
            self.logger.error(f"Agent '{self.name}' failed to execute task {task_id}: {e}")
            self.bus.publish(Event(f"agent.{self.name}.completed", {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "latency_ms": round(latency * 1000, 2)
            }, priority=0))

    def _on_broadcast_received(self, event: Event):
        """Handles general system-wide broadcasts."""
        pass

    def execute_task(self, payload: Dict[str, Any]) -> Any:
        """To be overridden by specific subclass agents."""
        raise NotImplementedError("Subclasses must implement execute_task.")

    def get_metrics(self) -> dict:
        avg_latency = (self.total_execution_time / self.processed_events_count * 1000) if self.processed_events_count > 0 else 0.0
        return {
            "name": self.name,
            "role": self.role,
            "processed_events": self.processed_events_count,
            "average_latency_ms": round(avg_latency, 2)
        }

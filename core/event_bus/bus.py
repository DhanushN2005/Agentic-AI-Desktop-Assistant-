import queue
import threading
import time
from collections.abc import Callable
from typing import Any
import logging


class Event:
    """Represents a standard event passing through the system."""
    def __init__(self, name: str, payload: dict[str, Any] = None, priority: int = 2):
        self.name = name
        self.payload = payload or {}
        self.priority = priority  # Lower is higher priority (0 = urgent, 3 = trace)
        self.timestamp = time.time()

    def __lt__(self, other):
        # Comparison for PriorityQueue
        return self.priority < other.priority

class EventBus:
    """Async, thread-safe Event Bus supporting Pub/Sub, priority queues, and event replays."""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._init_bus()
            return cls._instance

    def _init_bus(self):
        self.subscribers: dict[str, list[Callable[[Event], None]]] = {}
        self.event_history: list[Event] = []
        self.history_lock = threading.Lock()
        self.sub_lock = threading.Lock()
        self.queue = queue.PriorityQueue()
        self.stop_event = threading.Event()

        # Start async worker thread
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def subscribe(self, event_name: str, callback: Callable[[Event], None]):
        """Subscribe to a specific event topic."""
        with self.sub_lock:
            if event_name not in self.subscribers:
                self.subscribers[event_name] = []
            if callback not in self.subscribers[event_name]:
                self.subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Callable[[Event], None]):
        """Unsubscribe from an event topic."""
        with self.sub_lock:
            if event_name in self.subscribers and callback in self.subscribers[event_name]:
                self.subscribers[event_name].remove(callback)

    def publish(self, event: Event):
        """Enqueue an event for asynchronous dispatch."""
        # Log event in history
        with self.history_lock:
            self.event_history.append(event)
            if len(self.event_history) > 1000:  # Keep buffer reasonable
                self.event_history.pop(0)
        self.queue.put(event)

    def _worker(self):
        """Dedicated queue worker for dispatching events to subscribers."""
        while not self.stop_event.is_set():
            try:
                # Priority get with short timeout
                event = self.queue.get(timeout=0.1)
                self._dispatch(event)
                self.queue.task_done()
            except queue.Empty as _e:
                logging.debug("[core/event_bus/bus.py:75] Swallowed exception: %s: %s", type(_e).__name__, _e)
                continue
            except Exception as e:
                # NOTE: do NOT `import logging` here — that would shadow the
                # module-level import and make `logging` a local variable,
                # causing UnboundLocalError in the Empty handler above and
                # killing this worker thread on the first idle timeout.
                logging.getLogger("EventBus").error(f"Error in EventBus worker: {e}")

    def _dispatch(self, event: Event):
        """Internal direct dispatch helper."""
        callbacks = []
        with self.sub_lock:
            # Match specific event names or wildcard '*'
            if event.name in self.subscribers:
                callbacks.extend(self.subscribers[event.name])
            if "*" in self.subscribers:
                callbacks.extend(self.subscribers["*"])

        for callback in callbacks:
            try:
                callback(event)
            except Exception as ce:
                logging.getLogger("EventBus").error(f"Callback failure on event {event.name}: {ce}")

    def replay_events(self, count: int = 50) -> list[Event]:
        """Returns the last N events for auditing or debugging."""
        with self.history_lock:
            return list(self.event_history[-count:])

    def shutdown(self):
        """Safely stops the background worker thread."""
        self.stop_event.set()

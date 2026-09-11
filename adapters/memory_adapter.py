from engines.memory import MemoryEngine
from engines.long_term_memory import GlobalMemory
from core.event_bus.bus import EventBus, Event

class LegacyMemoryAdapter:
    """Bridges the SQLite MemoryEngine and GlobalMemory profile stores to standardized event notifications."""
    def __init__(self, memory_engine: MemoryEngine, global_memory: GlobalMemory):
        self.memory = memory_engine
        self.global_mem = global_memory
        self.bus = EventBus()

    def store(self, key: str, value: str, category: str = "general"):
        self.memory.store(key, value, category)
        self.bus.publish(Event("memory.store", {"key": key, "value": value, "category": category}))

    def recall(self, key: str) -> str:
        val = self.memory.recall(key)
        self.bus.publish(Event("memory.recall", {"key": key, "value": val}))
        return val

    def set_preference(self, key: str, value: str):
        self.global_mem.set_preference(key, value)
        self.bus.publish(Event("memory.preference.updated", {"key": key, "value": value}))

    def get_preference(self, key: str, default=None):
        return self.global_mem.get_preference(key, default)

    def log_activity(self, cmd: str):
        self.memory.log_activity(cmd)
        self.bus.publish(Event("memory.activity.logged", {"command": cmd}))

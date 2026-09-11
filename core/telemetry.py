import time
import logging
import json
from datetime import datetime
from utils.config import Config

class Telemetry:
    """Production-grade observability layer for Flexie 3.0."""
    def __init__(self):
        self.log_path = "flexie_telemetry.log"
        self.metrics = []

    def start_trace(self, command: str) -> dict:
        return {
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "start_time": time.perf_counter()
        }

    def end_trace(self, trace: dict, status: str = "success", error: str = None):
        latency = time.perf_counter() - trace["start_time"]
        entry = {
            "ts": trace["timestamp"],
            "cmd": trace["command"],
            "latency_ms": round(latency * 1000, 2),
            "status": status,
            "error": error
        }
        
        # Log to file
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
            
        print(f"[Telemetry] {entry['cmd']} -> {entry['latency_ms']}ms ({status})")
        return entry

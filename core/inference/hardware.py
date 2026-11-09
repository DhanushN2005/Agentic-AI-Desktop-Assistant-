"""Hardware-aware local model recommendation."""
from __future__ import annotations

import os
import platform
import subprocess

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a base dependency
    psutil = None


def _nvidia_gpu() -> dict:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            shell=False,
            check=False,
        )
        line = (result.stdout or "").strip().splitlines()[0]
        name, memory = [part.strip() for part in line.split(",", 1)]
        return {"name": name, "vram_gb": round(float(memory) / 1024, 1)}
    except Exception:
        return {}


def detect_hardware() -> dict:
    ram_gb = 0.0
    if psutil is not None:
        try:
            ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            ram_gb = 0.0
    gpu = _nvidia_gpu()
    return {
        "platform": platform.system(),
        "cpu_count": os.cpu_count() or 1,
        "ram_gb": round(ram_gb, 1),
        "gpu": gpu,
    }


def recommend_model(ram_gb: float, vram_gb: float = 0.0) -> str:
    if vram_gb >= 8:
        return "qwen2.5-coder:7b"
    if ram_gb >= 16:
        return "llama3.2:3b"
    if ram_gb >= 8:
        return "llama3.2:3b"
    return "llama3.2:1b"

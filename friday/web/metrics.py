"""Real hardware telemetry via psutil and nvidia-smi.

No values are synthesized. CPU/RAM come from psutil; GPU utilization, VRAM, and
temperature come from nvidia-smi when it is installed and a supported GPU is
present. When a metric is unavailable the corresponding field is ``None`` and a
reason is returned, never a fabricated number.
"""
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import psutil


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prime_cpu() -> None:
    """Seed psutil's CPU delta so the first real sample is meaningful."""
    try:
        psutil.cpu_percent(interval=None)
    except Exception:
        pass


def _gpu_metrics() -> Dict[str, Any]:
    unavailable = {
        "available": False,
        "name": None,
        "utilization_percent": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "memory_percent": None,
        "temperature_c": None,
        "provider": "nvidia-smi",
        "reason": "",
    }
    query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        unavailable["reason"] = "nvidia-smi not found; GPU telemetry unavailable."
        return unavailable
    except (OSError, subprocess.SubprocessError) as exc:
        unavailable["reason"] = f"nvidia-smi failed: {exc}"
        return unavailable

    if out.returncode != 0 or not out.stdout.strip():
        unavailable["reason"] = "nvidia-smi returned no GPU rows."
        return unavailable

    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]

    def _num(value: str) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    if len(parts) < 5:
        unavailable["reason"] = "Unexpected nvidia-smi output format."
        return unavailable

    used = _num(parts[2])
    total = _num(parts[3])
    percent = round(used / total * 100.0, 1) if used is not None and total else None
    return {
        "available": True,
        "name": parts[0],
        "utilization_percent": _num(parts[1]),
        "memory_used_mb": int(used) if used is not None else None,
        "memory_total_mb": int(total) if total is not None else None,
        "memory_percent": percent,
        "temperature_c": _num(parts[4]),
        "provider": "nvidia-smi",
        "reason": "",
    }


def system_metrics() -> Dict[str, Any]:
    """One non-blocking snapshot of CPU, RAM, disk, and GPU telemetry."""
    vm = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage(".")
        disk_payload = {
            "total_gb": round(disk.total / (1024 ** 3), 1),
            "used_gb": round(disk.used / (1024 ** 3), 1),
            "free_gb": round(disk.free / (1024 ** 3), 1),
            "percent": disk.percent,
        }
    except Exception:
        disk_payload = None

    try:
        cpu_count = psutil.cpu_count(logical=True)
        physical = psutil.cpu_count(logical=False)
    except Exception:
        cpu_count = physical = None

    return {
        "timestamp": _utc_now(),
        "cpu": {
            "percent": psutil.cpu_percent(interval=None),
            "logical_cores": cpu_count,
            "physical_cores": physical,
        },
        "ram": {
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "used_gb": round((vm.total - vm.available) / (1024 ** 3), 2),
            "available_gb": round(vm.available / (1024 ** 3), 2),
            "percent": vm.percent,
        },
        "disk": disk_payload,
        "gpu": _gpu_metrics(),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "source": "psutil+nvidia-smi",
    }

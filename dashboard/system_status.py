"""Collect local GPU, system, container, and log status."""

from __future__ import annotations

import os
import shutil
import socket
import sys
import subprocess
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def run_command(args: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def gpu_status() -> dict[str, Any]:
    args = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    result = run_command(args)
    if not result or result.returncode != 0:
        return {"available": False, "gpus": [], "message": "GPU status is unavailable."}

    gpus = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            continue
        total = _number(parts[1])
        used = _number(parts[2])
        gpus.append(
            {
                "name": parts[0],
                "memoryTotalMiB": total,
                "memoryUsedMiB": used,
                "memoryFreeMiB": _number(parts[3]),
                "memoryPercent": round((used / total) * 100, 1) if total else 0,
                "utilizationPercent": _number(parts[4]),
                "temperatureC": _number(parts[5]),
                "powerW": _number(parts[6]),
            }
        )
    return {"available": True, "gpus": gpus}


def system_status(project_dir: Path) -> dict[str, Any]:
    memory = _memory_status()
    uptime = _uptime_seconds()
    disk = _disk_status(project_dir)
    return {
        "host": socket.gethostname(),
        "memory": memory,
        "uptimeSeconds": uptime,
        "disk": disk,
    }


def docker_runtimes() -> list[dict[str, str]]:
    result = run_command(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}"]
    )
    if not result or result.returncode != 0:
        return []
    containers = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        if "vllm" not in " ".join(parts).lower():
            continue
        containers.append(
            {
                "containerId": parts[0],
                "containerName": parts[1],
                "status": parts[2],
                "ports": parts[3],
                "image": parts[4],
            }
        )
    return containers


def process_runtimes() -> list[dict[str, str]]:
    result = run_command(["pgrep", "-af", "vllm"])
    if not result or result.returncode != 0:
        return []
    processes = []
    for line in result.stdout.splitlines():
        if "pgrep" in line:
            continue
        pid, _, command = line.partition(" ")
        processes.append({"pid": pid, "command": command[:240]})
    return processes


def health_for_port(port: int) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/health"
    try:
        request = Request(url, headers={"User-Agent": "spark-dashboard"})
        with urlopen(request, timeout=1.5) as response:
            return {"url": url, "healthy": 200 <= response.status < 300, "status": response.status}
    except Exception:
        return {"url": url, "healthy": False, "status": None}


def docker_logs(container_name: str, lines: int) -> str:
    result = run_command(["docker", "logs", "--tail", str(lines), container_name], timeout=4.0)
    if not result:
        return "Logs are unavailable."
    return (result.stdout or "") + (result.stderr or "")


def stop_container(container_name: str) -> bool:
    result = run_command(["docker", "stop", container_name], timeout=10.0)
    return bool(result and result.returncode == 0)


def _memory_status() -> dict[str, Any]:
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            values[key] = int(raw.strip().split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        used = max(total - available, 0)
        return {
            "totalMiB": round(total / 1024),
            "usedMiB": round(used / 1024),
            "availableMiB": round(available / 1024),
            "usedPercent": round((used / total) * 100, 1) if total else 0,
        }
    if sys.platform == "win32":
        return _windows_memory_status()
    return {"totalMiB": 0, "usedMiB": 0, "availableMiB": 0, "usedPercent": 0}


def _uptime_seconds() -> float:
    uptime = Path("/proc/uptime")
    if not uptime.exists():
        return 0
    return float(uptime.read_text(encoding="utf-8").split()[0])


def _disk_status(project_dir: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(project_dir)
    total = usage.total
    free = usage.free
    used = total - free
    return {
        "totalGiB": round(total / (1024**3), 1),
        "usedGiB": round(used / (1024**3), 1),
        "freeGiB": round(free / (1024**3), 1),
        "usedPercent": round((used / total) * 100, 1) if total else 0,
    }


def _windows_memory_status() -> dict[str, Any]:
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"totalMiB": 0, "usedMiB": 0, "availableMiB": 0, "usedPercent": 0}
    total = status.ullTotalPhys
    available = status.ullAvailPhys
    used = max(total - available, 0)
    return {
        "totalMiB": round(total / (1024**2)),
        "usedMiB": round(used / (1024**2)),
        "availableMiB": round(available / (1024**2)),
        "usedPercent": round((used / total) * 100, 1) if total else 0,
    }


def _number(value: str) -> float:
    try:
        return float(value.replace(" W", ""))
    except ValueError:
        return 0

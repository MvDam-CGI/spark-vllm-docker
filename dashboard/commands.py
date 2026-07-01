"""Validate launch requests and build safe run-recipe.sh argument arrays."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .recipes import Recipe


PORT_MIN = 1024
PORT_MAX = 65535
HOST_PATTERN = re.compile(r"^[A-Za-z0-9:._-]+$")


@dataclass(frozen=True)
class LaunchPlan:
    command: list[str]
    runtime_id: str
    container_name: str
    port: int
    mode: str
    host: str


def build_launch_plan(project_dir: Path, recipe: Recipe, payload: dict[str, Any]) -> LaunchPlan:
    mode = str(payload.get("mode", "solo")).lower()
    if mode not in {"solo", "cluster"}:
        raise ValueError("Mode must be Solo or Cluster.")
    if recipe.cluster_only and mode == "solo":
        raise ValueError("This recipe requires Cluster mode.")
    if recipe.solo_only and mode == "cluster":
        raise ValueError("This recipe requires Solo mode.")

    port = _int_in_range(payload.get("port", recipe.default_port), PORT_MIN, PORT_MAX, "Port")
    host = _host(payload.get("host", recipe.default_host))
    gpu_memory = _float_in_range(
        payload.get("gpuMemoryUtilization", recipe.default_gpu_memory_utilization),
        0.1,
        0.98,
        "GPU memory utilization",
    )
    max_model_len = _int_in_range(
        payload.get("maxModelLen", recipe.default_max_model_len),
        1,
        1048576,
        "Max model length",
    )
    tensor_parallel = _int_in_range(payload.get("tensorParallel", 1), 1, 16, "Tensor parallel")
    setup = bool(payload.get("setup", False))
    dry_run = bool(payload.get("dryRun", False))

    runtime_id = f"{recipe.slug}-{port}"
    container_name = f"vllm-{recipe.slug}-{port}"
    script = project_dir / "run-recipe.sh"
    command = [
        str(script),
        recipe.slug,
        "--port",
        str(port),
        "--host",
        host,
        "--gpu-mem",
        str(gpu_memory),
        "--max-model-len",
        str(max_model_len),
        "--tp",
        str(tensor_parallel),
        "--name",
        container_name,
    ]
    command.append("--solo" if mode == "solo" else "--no-ray")
    if setup:
        command.append("--setup")
    if dry_run:
        command.append("--dry-run")

    return LaunchPlan(command, runtime_id, container_name, port, mode, host)


def _int_in_range(value: Any, minimum: int, maximum: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a whole number.") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _float_in_range(value: Any, minimum: float, maximum: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return number


def _host(value: Any) -> str:
    host = str(value or "").strip()
    if not host or len(host) > 255 or not HOST_PATTERN.match(host):
        raise ValueError("Host must be a valid host name or IP address.")
    return host

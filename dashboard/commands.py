"""Validate launch requests and build safe run-recipe.sh argument arrays."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .recipes import Recipe


PORT_MIN = 1024
PORT_MAX = 65535
HOST_PATTERN = re.compile(r"^[A-Za-z0-9:._-]+$")
CONTAINER_PATTERN = re.compile(r"^[A-Za-z0-9._:/@-]+$")
ENV_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.+$")
PATH_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._~:/\\-]+$")
PUBLISH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+:\d+$|^\d+:\d+$")
NCCL_DEBUG_LEVELS = {"VERSION", "WARN", "INFO", "TRACE"}


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
    max_num_batched_tokens = _optional_int_in_range(
        payload.get("maxNumBatchedTokens"),
        1,
        1048576,
        "Max batched tokens",
    )
    max_num_seqs = _optional_int_in_range(payload.get("maxNumSeqs"), 1, 65536, "Max sequences")
    tensor_parallel = _int_in_range(payload.get("tensorParallel", 1), 1, 16, "Tensor parallel")
    setup = bool(payload.get("setup", False))
    build_only = bool(payload.get("buildOnly", False))
    download_only = bool(payload.get("downloadOnly", False))
    dry_run = bool(payload.get("dryRun", False))
    nodes = _csv_hosts(payload.get("nodes"))
    container_override = _optional_pattern(payload.get("containerOverride"), CONTAINER_PATTERN, "Container override")
    nccl_debug = _optional_choice(payload.get("ncclDebug"), NCCL_DEBUG_LEVELS, "NCCL debug")
    env_vars = _list_values(payload.get("envVars"), ENV_PATTERN, "Environment variable")
    apply_mods = _list_values(payload.get("applyMods"), PATH_VALUE_PATTERN, "Apply mod path")
    publish_ports = _list_values(payload.get("publishPorts"), PUBLISH_PATTERN, "Published port")
    master_port = _optional_int_in_range(payload.get("masterPort"), PORT_MIN, PORT_MAX, "Master port")
    eth_if = _optional_pattern(payload.get("ethIf"), HOST_PATTERN, "Ethernet interface")
    ib_if = _optional_pattern(payload.get("ibIf"), HOST_PATTERN, "InfiniBand interface")
    build_jobs = _optional_int_in_range(payload.get("buildJobs"), 1, 256, "Build jobs")
    mem_limit = _optional_int_in_range(payload.get("memLimitGb"), 1, 4096, "Memory limit")
    mem_swap_limit = _optional_int_in_range(payload.get("memSwapLimitGb"), 1, 8192, "Memory swap limit")
    pids_limit = _optional_int_in_range(payload.get("pidsLimit"), 1, 1048576, "PIDs limit")
    shm_size = _optional_int_in_range(payload.get("shmSizeGb"), 1, 4096, "Shared memory size")
    extra_vllm_args = _extra_args(payload.get("extraVllmArgs"))
    if mode == "solo" and nodes:
        raise ValueError("Nodes are only used in Cluster mode.")
    if mode == "cluster" and publish_ports:
        raise ValueError("Published ports are only supported in Solo mode.")

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
        "--name",
        container_name,
    ]
    if max_num_batched_tokens:
        command.extend(["--max-num-batched-tokens", str(max_num_batched_tokens)])
    if max_num_seqs:
        command.extend(["--max-num-seqs", str(max_num_seqs)])
    command.extend(["--tp", str(tensor_parallel)])
    if container_override:
        command.extend(["--container", container_override])
    command.append("--solo" if mode == "solo" else "--no-ray")
    if nodes:
        command.extend(["--nodes", ",".join(nodes)])
    if setup:
        command.append("--setup")
    if build_only:
        command.append("--build-only")
    if download_only:
        command.append("--download-only")
    if payload.get("forceBuild"):
        command.append("--force-build")
    if payload.get("forceDownload"):
        command.append("--force-download")
    if payload.get("daemon"):
        command.append("--daemon")
    if nccl_debug:
        command.extend(["--nccl-debug", nccl_debug])
    for env_var in env_vars:
        command.extend(["--env", env_var])
    for mod in apply_mods:
        command.extend(["--apply-mod", mod])
    for port_mapping in publish_ports:
        command.extend(["--publish", port_mapping])
    if master_port:
        command.extend(["--master-port", str(master_port)])
    if eth_if:
        command.extend(["--eth-if", eth_if])
    if ib_if:
        command.extend(["--ib-if", ib_if])
    if build_jobs:
        command.extend(["-j", str(build_jobs)])
    if payload.get("noCacheDirs"):
        command.append("--no-cache-dirs")
    if payload.get("keepEntrypoint"):
        command.append("--keep-entrypoint")
    if payload.get("nonPrivileged"):
        command.append("--non-privileged")
    if mem_limit:
        command.extend(["--mem-limit-gb", str(mem_limit)])
    if mem_swap_limit:
        command.extend(["--mem-swap-limit-gb", str(mem_swap_limit)])
    if pids_limit:
        command.extend(["--pids-limit", str(pids_limit)])
    if shm_size:
        command.extend(["--shm-size-gb", str(shm_size)])
    if dry_run:
        command.append("--dry-run")
    if extra_vllm_args:
        command.append("--")
        command.extend(extra_vllm_args)

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


def _optional_int_in_range(value: Any, minimum: int, maximum: int, label: str) -> int | None:
    if value in (None, ""):
        return None
    return _int_in_range(value, minimum, maximum, label)


def _optional_pattern(value: Any, pattern: re.Pattern[str], label: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > 255 or not pattern.match(text):
        raise ValueError(f"{label} is invalid.")
    return text


def _optional_choice(value: Any, choices: set[str], label: str) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if text not in choices:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(choices))}.")
    return text


def _csv_hosts(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    hosts = [part.strip() for part in text.split(",") if part.strip()]
    if len(hosts) < 2:
        raise ValueError("Cluster nodes must include at least two hosts.")
    for host in hosts:
        _host(host)
    return hosts


def _list_values(value: Any, pattern: re.Pattern[str], label: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be provided as a list.")
    items = [str(item).strip() for item in value if str(item).strip()]
    for item in items:
        if len(item) > 512 or not pattern.match(item):
            raise ValueError(f"{label} is invalid: {item}")
    return items


def _extra_args(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        args = shlex.split(text)
    except ValueError as exc:
        raise ValueError("Extra vLLM arguments are not valid shell-style arguments.") from exc
    if any(arg == "--" for arg in args):
        raise ValueError("Do not include the -- separator in extra vLLM arguments.")
    return args


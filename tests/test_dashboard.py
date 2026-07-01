from pathlib import Path
from subprocess import CompletedProcess

import pytest

from dashboard import server

from dashboard.commands import build_launch_plan
from dashboard.recipes import load_recipe
from dashboard.system_status import gpu_status, system_status

PROJECT_DIR = Path(__file__).resolve().parents[1]

def test_load_recipe_normalizes_translategemma():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "translategemma-4b-it.yaml")

    assert recipe.slug == "translategemma-4b-it"
    assert recipe.name == "TranslateGemma-4B-IT"
    assert recipe.default_port == 8000
    assert recipe.solo_only is True

def test_build_launch_plan_uses_argument_array():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "translategemma-4b-it.yaml")

    plan = build_launch_plan(
        PROJECT_DIR,
        recipe,
        {
            "mode": "solo",
            "port": 8001,
            "host": "0.0.0.0",
            "gpuMemoryUtilization": 0.7,
            "maxModelLen": 2048,
            "tensorParallel": 1,
            "dryRun": True,
        },
    )

    assert plan.command[:3] == [str(PROJECT_DIR / "run-recipe.sh"), "translategemma-4b-it", "--port"]
    assert "--solo" in plan.command
    assert "--dry-run" in plan.command
    assert "8001" in plan.command
    assert plan.container_name == "vllm-translategemma-4b-it-8001"

def test_build_launch_plan_rejects_invalid_port():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "translategemma-4b-it.yaml")

    with pytest.raises(ValueError, match="Port must be between"):
        build_launch_plan(PROJECT_DIR, recipe, {"mode": "solo", "port": 80})

def test_build_launch_plan_rejects_cluster_for_solo_only_recipe():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "translategemma-4b-it.yaml")

    with pytest.raises(ValueError, match="requires Solo mode"):
        build_launch_plan(PROJECT_DIR, recipe, {"mode": "cluster", "port": 8001})

def test_system_status_returns_memory_and_disk():
    status = system_status(PROJECT_DIR)

    assert "usedPercent" in status["memory"]
    assert status["disk"]["freeGiB"] >= 0

def test_gpu_status_falls_back_to_process_table(monkeypatch):
    sample = """
|   0  NVIDIA GB10                    On  |   0000000F:01:00.0 Off |                  N/A |
| N/A   44C    P0             11W /  N/A  | Not Supported          |      0%      Default |
|    0   N/A  N/A           34988      G   /usr/lib/xorg/Xorg                       69MiB |
|    0   N/A  N/A           35147      G   /usr/bin/gnome-shell                     67MiB |
|    0   N/A  N/A         3454041      C   VLLM::EngineCore                      58450MiB |
"""

    def fake_run_command(args, timeout=2.0):
        if "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw" in args:
            return CompletedProcess(args, 0, "NVIDIA GB10, Not Supported, Not Supported, Not Supported, 0, 44, 11\n", "")
        if args == ["nvidia-smi"]:
            return CompletedProcess(args, 0, sample, "")
        return CompletedProcess(args, 1, "", "")

    monkeypatch.setattr("dashboard.system_status.run_command", fake_run_command)

    status = gpu_status()

    assert status["available"] is True
    assert status["gpus"][0]["memoryUsedMiB"] == 58586
    assert status["gpus"][0]["memoryPercent"] == 44.7
    assert status["gpus"][0]["memorySource"] == "process-table"
    assert status["gpus"][0]["memoryTotalMiB"] == 131072

def test_current_runtimes_marks_registry_only_runtime_stopped(monkeypatch):
    monkeypatch.setattr(server.REGISTRY, "list", lambda: [{"id": "old", "port": 8001, "status": "Starting"}])
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: False)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": False})

    runtimes = server.current_runtimes()

    assert runtimes[0]["status"] == "Stopped"

def test_runtime_logs_strips_ansi(monkeypatch):
    log_path = PROJECT_DIR / "dashboard" / "state" / "test-runtime.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\x1b[0;36mINFO\x1b[0m startup\n", encoding="utf-8")
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "\x1b[31mERROR\x1b[0m failed")

    try:
        logs = server.runtime_logs({"logPath": str(log_path), "containerName": "vllm-test"}, 20)
    finally:
        log_path.unlink(missing_ok=True)

    assert "\x1b" not in logs
    assert "INFO startup" in logs
    assert "ERROR failed" in logs

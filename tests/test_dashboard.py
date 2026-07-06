from pathlib import Path
import shutil
from subprocess import CompletedProcess

import pytest

from dashboard import server
from dashboard import metrics as dashboard_metrics
from dashboard import system_status as system_status_helpers

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
    assert plan.runtime_id.startswith("translategemma-4b-it-8001-")
    assert plan.runtime_id != "translategemma-4b-it-8001"
    assert plan.container_name == f"vllm-{plan.runtime_id}"


def test_build_launch_plan_creates_unique_runtime_ids_for_same_port():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "translategemma-4b-it.yaml")
    payload = {
        "mode": "solo",
        "port": 8001,
        "host": "0.0.0.0",
        "gpuMemoryUtilization": 0.7,
        "maxModelLen": 2048,
        "tensorParallel": 1,
        "dryRun": True,
    }

    first = build_launch_plan(PROJECT_DIR, recipe, payload)
    second = build_launch_plan(PROJECT_DIR, recipe, payload)

    assert first.runtime_id != second.runtime_id
    assert first.container_name != second.container_name
    assert first.container_name == f"vllm-{first.runtime_id}"
    assert second.container_name == f"vllm-{second.runtime_id}"


def test_project_name_trims_whitespace_and_length():
    assert server._project_name("  Demo   Run  ") == "Demo Run"
    assert len(server._project_name("x" * 100)) == 80

def test_model_availability_detects_huggingface_snapshot(monkeypatch):
    cache = PROJECT_DIR / "dashboard" / "state" / "test-hf-cache"
    shutil.rmtree(cache, ignore_errors=True)
    snapshot = cache / "hub" / "models--org--model" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(cache))

    try:
        availability = server.model_availability("org/model")
    finally:
        shutil.rmtree(cache, ignore_errors=True)

    assert availability["downloaded"] is True
    assert availability["status"] == "downloaded"


def test_model_availability_reports_missing_huggingface_snapshot(monkeypatch):
    cache = PROJECT_DIR / "dashboard" / "state" / "missing-hf-cache"
    shutil.rmtree(cache, ignore_errors=True)
    monkeypatch.setenv("HF_HOME", str(cache))

    availability = server.model_availability("org/model")

    assert availability["downloaded"] is False
    assert availability["status"] == "missing"

def test_build_launch_plan_includes_advanced_options():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "glm-4.7-flash-awq.yaml")

    plan = build_launch_plan(
        PROJECT_DIR,
        recipe,
        {
            "mode": "cluster",
            "port": 8002,
            "host": "0.0.0.0",
            "gpuMemoryUtilization": 0.82,
            "maxModelLen": 8192,
            "maxNumBatchedTokens": 4096,
            "maxNumSeqs": 64,
            "tensorParallel": 2,
            "nodes": "10.0.0.1,10.0.0.2",
            "containerOverride": "vllm-node:test",
            "ncclDebug": "INFO",
            "envVars": ["VLLM_LOGGING_LEVEL=DEBUG"],
            "applyMods": ["mods/test-mod"],
            "masterPort": 29501,
            "ethIf": "eth0",
            "ibIf": "ib0",
            "buildJobs": 8,
            "noCacheDirs": True,
            "keepEntrypoint": True,
            "nonPrivileged": True,
            "memLimitGb": 120,
            "memSwapLimitGb": 128,
            "pidsLimit": 4096,
            "shmSizeGb": 64,
            "buildOnly": True,
            "forceBuild": True,
            "dryRun": True,
            "extraVllmArgs": "--load-format auto --seed 42",
        },
    )

    assert "--no-ray" in plan.command
    assert plan.command[plan.command.index("--nodes") + 1] == "10.0.0.1,10.0.0.2"
    assert plan.command[plan.command.index("--max-num-batched-tokens") + 1] == "4096"
    assert plan.command[plan.command.index("--max-num-seqs") + 1] == "64"
    assert plan.command[plan.command.index("--container") + 1] == "vllm-node:test"
    assert plan.command[plan.command.index("--env") + 1] == "VLLM_LOGGING_LEVEL=DEBUG"
    assert plan.command[plan.command.index("--apply-mod") + 1] == "mods/test-mod"
    assert "--build-only" in plan.command
    assert "--force-build" in plan.command
    assert "--no-cache-dirs" in plan.command
    assert "--keep-entrypoint" in plan.command
    assert "--non-privileged" in plan.command
    assert plan.command[-5:] == ["--", "--load-format", "auto", "--seed", "42"]


def test_build_launch_plan_rejects_publish_ports_in_cluster_mode():
    recipe = load_recipe(PROJECT_DIR / "recipes" / "glm-4.7-flash-awq.yaml")

    with pytest.raises(ValueError, match="Published ports"):
        build_launch_plan(
            PROJECT_DIR,
            recipe,
            {
                "mode": "cluster",
                "port": 8002,
                "host": "0.0.0.0",
                "gpuMemoryUtilization": 0.82,
                "maxModelLen": 8192,
                "publishPorts": ["8000:8000"],
            },
        )
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

def test_current_runtimes_adds_only_manual_vllm_server_processes(monkeypatch):
    monkeypatch.setattr(server.REGISTRY, "list", lambda: [])
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "gpu_status", lambda: {"gpus": []})
    monkeypatch.setattr(
        server,
        "process_runtimes",
        lambda: [
            {"pid": "123", "command": "vllm serve Infomaniak-AI/vllm-translategemma-4b-it", "port": "8005"},
            {"pid": "126", "command": "vllm serve Infomaniak-AI/vllm-translategemma-4b-it", "port": "8005"},
            {"pid": "124", "command": "VLLM::EngineCore"},
            {"pid": "125", "command": "python -m multiprocessing.spawn vllm worker"},
        ],
    )

    runtimes = server.current_runtimes()

    assert len(runtimes) == 1
    assert runtimes[0] | {"startedAt": None, "updatedAt": None} == {
        "id": "manual-vllm-123",
        "recipeSlug": "translategemma-4b-it",
        "recipeName": "TranslateGemma-4B-IT",
        "status": "Running",
        "mode": "Manual",
        "port": "8005",
        "processId": "123",
        "processCommand": "vllm serve Infomaniak-AI/vllm-translategemma-4b-it",
        "health": {"url": "http://127.0.0.1:8005/health", "healthy": False, "status": None},
        "memoryBreakdown": {"modelMiB": None, "contextMiB": None},
        "startedAt": None,
        "updatedAt": None,
    }


def test_process_runtimes_includes_listening_port(monkeypatch):
    def fake_run_command(args, timeout=2.0):
        if args == ["pgrep", "-af", "vllm"]:
            return CompletedProcess(args, 0, "123 vllm serve model\n", "")
        if args == ["ss", "-ltnp"]:
            return CompletedProcess(args, 0, "LISTEN 0 4096 0.0.0.0:8005 0.0.0.0:* users:((\"python\",pid=123,fd=7))\n", "")
        return CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(system_status_helpers, "run_command", fake_run_command)

    assert system_status_helpers.process_runtimes() == [{"pid": "123", "command": "vllm serve model", "port": "8005"}]


def test_process_runtimes_keeps_full_command_for_port_parsing(monkeypatch):
    long_command = "vllm serve " + ("x" * 260) + " --port 8005"

    def fake_run_command(args, timeout=2.0):
        if args == ["pgrep", "-af", "vllm"]:
            return CompletedProcess(args, 0, f"123 {long_command}\n", "")
        if args == ["ss", "-ltnp"]:
            return CompletedProcess(args, 1, "", "")
        return CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(system_status_helpers, "run_command", fake_run_command)

    assert system_status_helpers.process_runtimes() == [{"pid": "123", "command": long_command}]


def test_current_runtimes_suppresses_manual_process_matching_registered_runtime(monkeypatch):
    monkeypatch.setattr(
        server.REGISTRY,
        "list",
        lambda: [
            {
                "id": "translategemma-4b-it-8005",
                "recipeSlug": "translategemma-4b-it",
                "recipeName": "TranslateGemma-4B-IT",
                "port": 8005,
                "status": "Starting",
                "processId": "319777",
            }
        ],
    )
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: True)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": True})
    monkeypatch.setattr(server, "gpu_status", lambda: {"gpus": []})
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "")
    monkeypatch.setattr(
        server,
        "process_runtimes",
        lambda: [
            {
                "pid": "319917",
                "command": "/usr/bin/python3 /usr/local/bin/vllm serve Infomaniak-AI/vllm-translategemma-4b-it --port 8005",
            }
        ],
    )

    runtimes = server.current_runtimes()

    assert len(runtimes) == 1
    assert runtimes[0]["id"] == "translategemma-4b-it-8005"


def test_gpu_memory_target_prefers_actual_launch_command():
    runtime = {"gpuMemoryUtilization": 0.45, "command": ["./run-recipe.sh", "model", "--gpu-mem", "0.4"]}

    assert server._gpu_memory_target_percent(runtime) == 40


def test_stop_vllm_process_requires_current_vllm_command(monkeypatch):
    killed = []

    monkeypatch.setattr(
        system_status_helpers,
        "run_command",
        lambda args, timeout=2.0: CompletedProcess(args, 0, "python worker.py\n", ""),
    )
    monkeypatch.setattr(system_status_helpers.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    assert system_status_helpers.stop_vllm_process(123) is False
    assert killed == []


def test_stop_vllm_process_sends_sigterm_to_vllm_command(monkeypatch):
    killed = []

    monkeypatch.setattr(
        system_status_helpers,
        "run_command",
        lambda args, timeout=2.0: CompletedProcess(args, 0, "vllm serve test-model\n", ""),
    )
    monkeypatch.setattr(system_status_helpers.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    assert system_status_helpers.stop_vllm_process("123") is True
    assert killed == [(123, system_status_helpers.signal.SIGTERM)]


def test_stop_vllm_process_sends_sigterm_to_dashboard_launch_wrapper(monkeypatch):
    killed = []

    monkeypatch.setattr(
        system_status_helpers,
        "run_command",
        lambda args, timeout=2.0: CompletedProcess(args, 0, "bash ./run-recipe.sh translategemma-4b-it --port 8003\n", ""),
    )
    monkeypatch.setattr(system_status_helpers.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    assert system_status_helpers.stop_vllm_process("123") is True
    assert killed == [(123, system_status_helpers.signal.SIGTERM)]

def test_current_runtimes_marks_registry_only_runtime_exited(monkeypatch):
    monkeypatch.setattr(server.REGISTRY, "list", lambda: [{"id": "old", "port": 8001, "status": "Starting"}])
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: False)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": False})
    monkeypatch.setattr(server, "gpu_status", lambda: {"gpus": []})
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "")

    runtimes = server.current_runtimes()

    assert runtimes[0]["status"] == "Exited"


def test_current_runtimes_does_not_mark_stale_runtime_ready_from_reused_port(monkeypatch):
    monkeypatch.setattr(
        server.REGISTRY,
        "list",
        lambda: [{"id": "old-translategemma", "port": 8003, "status": "Starting", "processId": "123"}],
    )
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: False)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": True})
    monkeypatch.setattr(server, "gpu_status", lambda: {"gpus": []})
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "")

    runtimes = server.current_runtimes()

    assert runtimes[0]["status"] == "Exited"

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

def test_current_runtimes_keeps_manual_stop_reason(monkeypatch):
    monkeypatch.setattr(server.REGISTRY, "list", lambda: [{"id": "old", "port": 8001, "status": "Manually Stopped", "stopRequestedAt": "now"}])
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: False)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": False})
    monkeypatch.setattr(server, "gpu_status", lambda: {"gpus": []})
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "")

    runtimes = server.current_runtimes()

    assert runtimes[0]["status"] == "Manually Stopped"

def test_current_runtimes_uses_configured_gpu_target_for_multiple_active(monkeypatch):
    monkeypatch.setattr(
        server.REGISTRY,
        "list",
        lambda: [
            {"id": "one", "port": 8001, "status": "Starting", "gpuMemoryUtilization": 0.7},
            {"id": "two", "port": 8002, "status": "Starting", "command": ["run", "--gpu-mem", "0.2"]},
        ],
    )
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: True)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": False})
    monkeypatch.setattr(
        server,
        "gpu_status",
        lambda: {"gpus": [{"memoryTotalMiB": 131072, "processes": [{"name": "VLLM::EngineCore", "memoryMiB": 60000}]}]},
    )
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "")

    runtimes = server.current_runtimes()

    assert [runtime["gpuMemoryPercent"] for runtime in runtimes] == [70, 20]
    assert all(runtime["gpuMemorySource"] == "configured target" for runtime in runtimes)

def test_merge_memory_breakdown_keeps_values_when_tail_omits_them():
    stored = {"modelMiB": 7680, "contextMiB": 28928}
    parsed = {"modelMiB": None, "contextMiB": None}

    assert dashboard_metrics.merge_memory_breakdown(stored, parsed) == stored

def test_current_runtimes_persists_new_memory_breakdown(monkeypatch):
    updates = []
    monkeypatch.setattr(
        server.REGISTRY,
        "list",
        lambda: [{"id": "one", "port": 8001, "status": "Starting", "memoryBreakdown": {"modelMiB": 7680, "contextMiB": None}}],
    )
    monkeypatch.setattr(server.REGISTRY, "update_fields", lambda runtime_id, payload: updates.append((runtime_id, payload)))
    monkeypatch.setattr(server, "docker_runtimes", lambda: [])
    monkeypatch.setattr(server, "_process_running", lambda pid: True)
    monkeypatch.setattr(server, "health_for_port", lambda port: {"healthy": False})
    monkeypatch.setattr(server, "gpu_status", lambda: {"gpus": []})
    monkeypatch.setattr(server, "docker_logs", lambda container_name, lines: "GPU KV cache size: 28.25GiB")

    runtimes = server.current_runtimes()

    assert runtimes[0]["memoryBreakdown"] == {"modelMiB": 7680, "contextMiB": 28928}
    assert updates == [("one", {"memoryBreakdown": {"modelMiB": 7680, "contextMiB": 28928}})]
def test_parse_memory_breakdown_handles_vllm_gb_lines():
    logs = "Model loading took 8.2 GiB memory\nGPU KV cache size: 28.25GiB\n"

    breakdown = dashboard_metrics.parse_memory_breakdown(logs)

    assert breakdown["modelMiB"] == 8396.8
    assert breakdown["contextMiB"] == 28928


def test_parse_prometheus_token_metrics_sums_labeled_vllm_counters():
    text = """
# HELP vllm:prompt_tokens_total Number of prefill tokens processed.
vllm:prompt_tokens_total{model_name="one"} 100
vllm:prompt_tokens_total{model_name="two"} 25
vllm:generation_tokens_total{model_name="one"} 300
vllm:generation_tokens_total{model_name="two"} 75
vllm:request_success_total{finished_reason="stop",model_name="one"} 3
vllm:request_success_total{finished_reason="stop",model_name="two"} 2
vllm:num_requests_running{model_name="one"} 2
vllm:num_requests_waiting{model_name="one"} 1
vllm:request_time_per_output_token_seconds_sum{model_name="one"} 1.5
vllm:request_time_per_output_token_seconds_sum{model_name="two"} 0.5
vllm:request_time_per_output_token_seconds_count{model_name="one"} 3
vllm:request_time_per_output_token_seconds_count{model_name="two"} 2
vllm:e2e_request_latency_seconds_sum{model_name="one"} 12
vllm:e2e_request_latency_seconds_count{model_name="one"} 3
vllm:kv_cache_usage_perc{model_name="one"} 0.25
vllm:prefix_cache_queries_total{model_name="one"} 100
vllm:prefix_cache_hits_total{model_name="one"} 60
"""

    metrics = dashboard_metrics.parse_prometheus_token_metrics(text)

    assert metrics == {
        "source": "prometheus",
        "promptTokensTotal": 125,
        "generationTokensTotal": 375,
        "tokensTotal": 500,
        "requestCount": 5,
        "runningRequestCount": 2,
        "waitingRequestCount": 1,
        "timePerOutputTokenMs": 400.0,
        "interTokenLatencyMs": None,
        "endToEndLatencySeconds": 4.0,
        "kvCacheUsagePercent": 25.0,
        "prefixCacheHitPercent": 60.0,
    }


def test_merge_token_metrics_calculates_observed_generation_rate():
    stored = {
        "source": "prometheus",
        "sampledAt": "2026-07-03T15:19:54+00:00",
        "generationTokensTotal": 0,
        "lastActiveGeneratedTokensPerSecond": None,
        "peakGeneratedTokensPerSecond": None,
    }
    current = {
        "source": "prometheus",
        "sampledAt": "2026-07-03T15:20:04+00:00",
        "promptTokensTotal": 5757,
        "generationTokensTotal": 6279,
        "tokensTotal": 12036,
    }

    metrics = dashboard_metrics.merge_token_metrics(stored, current)

    assert metrics["currentGeneratedTokensPerSecond"] == 627.9
    assert metrics["lastActiveGeneratedTokensPerSecond"] == 627.9
    assert metrics["peakGeneratedTokensPerSecond"] == 627.9


def test_merge_token_metrics_keeps_last_active_rate_when_idle():
    stored = {
        "source": "prometheus",
        "sampledAt": "2026-07-03T15:20:04+00:00",
        "generationTokensTotal": 6279,
        "lastActiveGeneratedTokensPerSecond": 627.9,
        "peakGeneratedTokensPerSecond": 627.9,
    }
    current = {
        "source": "prometheus",
        "sampledAt": "2026-07-03T15:20:14+00:00",
        "promptTokensTotal": 5757,
        "generationTokensTotal": 6279,
        "tokensTotal": 12036,
    }

    metrics = dashboard_metrics.merge_token_metrics(stored, current)

    assert metrics["currentGeneratedTokensPerSecond"] == 0
    assert metrics["lastActiveGeneratedTokensPerSecond"] == 627.9
    assert metrics["peakGeneratedTokensPerSecond"] == 627.9

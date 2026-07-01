"""Serve the local DGX Spark vLLM dashboard."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .commands import build_launch_plan
from .recipes import recipe_map
from .runtime_state import RuntimeRegistry, utc_now
from .system_status import (
    docker_logs,
    docker_runtimes,
    gpu_status,
    health_for_port,
    process_runtimes,
    stop_container,
    system_status,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATE_DIR = Path(__file__).resolve().parent / "state"
LOG_DIR = STATE_DIR / "logs"
REGISTRY = RuntimeRegistry(STATE_DIR / "runtimes.json")
TOKEN_FILE = STATE_DIR / "control-token.txt"


def ensure_token() -> str:
    env_token = os.environ.get("DASHBOARD_TOKEN")
    if env_token:
        return env_token
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


CONTROL_TOKEN = ensure_token()


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "SparkDashboard/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path in {"/", "/overview", "/recipes", "/runtime", "/launch", "/logs", "/settings"}:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._json({"error": "A valid dashboard token is required."}, HTTPStatus.UNAUTHORIZED)
            return
        payload = self._read_json()
        try:
            self._handle_api_post(parsed.path, payload)
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/recipes":
            self._json({"recipes": [recipe.to_api() for recipe in recipe_map(PROJECT_DIR).values()]})
        elif path == "/api/runtimes":
            self._json({"runtimes": current_runtimes(), "containers": docker_runtimes(), "processes": process_runtimes()})
        elif path == "/api/gpu":
            self._json(gpu_status())
        elif path == "/api/system":
            self._json(system_status(PROJECT_DIR))
        elif path == "/api/settings":
            self._json(settings_status())
        elif path.startswith("/api/logs/"):
            runtime_id = path.removeprefix("/api/logs/")
            lines = int((query.get("lines") or ["200"])[0])
            runtime = REGISTRY.get(runtime_id)
            if not runtime:
                self._json({"error": "Runtime was not found."}, HTTPStatus.NOT_FOUND)
                return
            logs = runtime_logs(runtime, max(20, min(lines, 1000)))
            self._json({"runtimeId": runtime_id, "logs": logs, "events": clean_events(logs)})
        else:
            self._json({"error": "API route was not found."}, HTTPStatus.NOT_FOUND)

    def _handle_api_post(self, path: str, payload: dict[str, Any]) -> None:
        if path == "/api/runtimes":
            recipes = recipe_map(PROJECT_DIR)
            slug = str(payload.get("recipeSlug", ""))
            recipe = recipes.get(slug)
            if not recipe:
                raise ValueError("Unknown recipe.")
            plan = build_launch_plan(PROJECT_DIR, recipe, payload)
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = LOG_DIR / f"{plan.runtime_id}.log"
            runtime = {
                "id": plan.runtime_id,
                "recipeSlug": recipe.slug,
                "recipeName": recipe.name,
                "command": plan.command,
                "port": plan.port,
                "host": plan.host,
                "mode": plan.mode,
                "gpuMemoryUtilization": payload.get("gpuMemoryUtilization"),
                "maxModelLen": payload.get("maxModelLen"),
                "tensorParallel": payload.get("tensorParallel"),
                "containerName": plan.container_name,
                "logPath": str(log_path),
                "status": "Dry Run" if payload.get("dryRun") else "Starting",
                "startedAt": utc_now(),
                "updatedAt": utc_now(),
            }
            if payload.get("dryRun"):
                result = subprocess.run(plan.command, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60)
                output = result.stdout[-8000:] + result.stderr[-2000:]
                log_path.write_text(output, encoding="utf-8")
                runtime["lastOutput"] = output
                runtime["status"] = "Ready" if result.returncode == 0 else "Needs Attention"
                REGISTRY.upsert(runtime)
                self._json({"launchId": plan.runtime_id, "status": runtime["status"], "command": plan.command, "output": output})
                return
            log_file = log_path.open("ab")
            try:
                process = subprocess.Popen(
                    plan.command,
                    cwd=PROJECT_DIR,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            finally:
                log_file.close()
            runtime["processId"] = process.pid
            REGISTRY.upsert(runtime)
            self._json(
                {
                    "launchId": plan.runtime_id,
                    "status": "Starting",
                    "command": plan.command,
                    "logsPath": f"/api/logs/{plan.runtime_id}",
                },
                HTTPStatus.ACCEPTED,
            )
        elif path.startswith("/api/runtimes/") and path.endswith("/stop"):
            runtime_id = path.removeprefix("/api/runtimes/").removesuffix("/stop")
            runtime = REGISTRY.get(runtime_id)
            if not runtime:
                self._json({"error": "Runtime was not found."}, HTTPStatus.NOT_FOUND)
                return
            stopped = stop_container(str(runtime.get("containerName", "")))
            if stopped:
                REGISTRY.update_status(runtime_id, "Manually Stopped", {"stopRequestedAt": utc_now(), "stopReason": "dashboard"})
            else:
                REGISTRY.update_status(runtime_id, "Needs Attention")
            self._json({"runtimeId": runtime_id, "stopped": stopped})
        else:
            self._json({"error": "API route was not found."}, HTTPStatus.NOT_FOUND)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _authorized(self) -> bool:
        token = self.headers.get("X-Dashboard-Token", "")
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        same_origin = not origin or origin.endswith(host or "")
        return same_origin and secrets.compare_digest(token, CONTROL_TOKEN)

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def current_runtimes() -> list[dict[str, Any]]:
    containers = {item["containerName"]: item for item in docker_runtimes()}
    runtimes = []
    gpu = gpu_status()
    for runtime in REGISTRY.list():
        item = dict(runtime)
        container = containers.get(str(item.get("containerName", "")))
        process_running = _process_running(item.get("processId"))
        port = int(item.get("port", 0) or 0)
        item["health"] = health_for_port(port) if port else {"healthy": False}
        item["gpuMemoryTargetPercent"] = _gpu_memory_target_percent(item)
        manual_stop = item.get("status") == "Manually Stopped" or bool(item.get("stopRequestedAt"))
        if item["health"].get("healthy"):
            item["status"] = "Ready"
        elif container:
            item["status"] = "Starting" if "Up" in container.get("status", "") else "Needs Attention"
            item["container"] = container
        elif process_running:
            item["status"] = "Starting"
        elif item.get("status") == "Dry Run":
            item["status"] = "Dry Run"
        elif manual_stop:
            item["status"] = "Manually Stopped"
        else:
            item["status"] = "Exited"
        logs = runtime_logs(item, 80)
        parsed_memory = parse_memory_breakdown(logs)
        item["memoryBreakdown"] = merge_memory_breakdown(item.get("memoryBreakdown"), parsed_memory)
        if _has_new_memory_values(item.get("memoryBreakdown"), runtime.get("memoryBreakdown")):
            REGISTRY.update_fields(str(item.get("id")), {"memoryBreakdown": item["memoryBreakdown"]})
        runtimes.append(item)
    _assign_gpu_memory(runtimes, gpu)
    return runtimes


def runtime_logs(runtime: dict[str, Any], lines: int) -> str:
    parts = []
    startup = _tail_file(Path(str(runtime.get("logPath", ""))), lines)
    if startup:
        parts.append("=== Startup logs ===\n" + startup)
    container_logs = docker_logs(str(runtime.get("containerName", "")), lines)
    if container_logs:
        parts.append("=== Container logs ===\n" + container_logs)
    merged = "\n\n".join(parts) if parts else "Logs are not available yet. The runtime may still be preparing its container."
    return strip_ansi(merged)


def clean_events(logs: str) -> list[dict[str, str]]:
    events = []
    seen = set()
    keywords = (
        ("error", "Error"),
        ("failed", "Error"),
        ("exception", "Error"),
        ("traceback", "Error"),
        ("ready", "Ready"),
        ("running", "Running"),
        ("starting", "Starting"),
        ("launching", "Starting"),
    )
    for line in strip_ansi(logs).splitlines()[-240:]:
        cleaned = " ".join(line.split())
        if not cleaned:
            continue
        lower = cleaned.lower()
        match = next((label for word, label in keywords if word in lower), None)
        if not match:
            continue
        message = cleaned[-220:]
        key = (match, message)
        if key in seen:
            continue
        seen.add(key)
        events.append({"status": match, "message": message})
    return events[-8:]


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MEMORY_PATTERNS = (
    ("modelMiB", re.compile(r"(?:loading model weights|model weights|model memory|weights).*?(\d+(?:\.\d+)?)\s*(GiB|GB|MiB|MB)", re.IGNORECASE)),
    ("contextMiB", re.compile(r"(?:kv cache|context|cache).*?(\d+(?:\.\d+)?)\s*(GiB|GB|MiB|MB)", re.IGNORECASE)),
)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\x1b", "")


def parse_memory_breakdown(logs: str) -> dict[str, Any]:
    breakdown: dict[str, Any] = {"modelMiB": None, "contextMiB": None}
    clean = strip_ansi(logs)
    for key, pattern in MEMORY_PATTERNS:
        match = pattern.search(clean)
        if match:
            amount = float(match.group(1))
            unit = match.group(2).lower()
            breakdown[key] = round(amount * 1024 if unit.startswith("g") else amount, 1)
    return breakdown

def merge_memory_breakdown(stored: Any, parsed: dict[str, Any]) -> dict[str, Any]:
    stored_values = stored if isinstance(stored, dict) else {}
    merged = {"modelMiB": stored_values.get("modelMiB"), "contextMiB": stored_values.get("contextMiB")}
    for key in merged:
        if parsed.get(key) is not None:
            merged[key] = parsed[key]
    return merged


def _has_new_memory_values(current: Any, previous: Any) -> bool:
    if not isinstance(current, dict):
        return False
    previous_values = previous if isinstance(previous, dict) else {}
    for key, value in current.items():
        if value is not None and previous_values.get(key) != value:
            return True
    return False
def _assign_gpu_memory(runtimes: list[dict[str, Any]], gpu: dict[str, Any]) -> None:
    active = [item for item in runtimes if item.get("status") in {"Starting", "Running", "Ready"}]
    for runtime in active:
        target = runtime.get("gpuMemoryTargetPercent")
        if target is not None:
            runtime["gpuMemoryPercent"] = target
            runtime["gpuMemorySource"] = "configured target"

    processes = (gpu.get("gpus") or [{}])[0].get("processes") or []
    vllm_processes = [process for process in processes if "vllm" in str(process.get("name", "")).lower()]
    total = (gpu.get("gpus") or [{}])[0].get("memoryTotalMiB")
    if len(active) != 1 or not vllm_processes:
        return
    used = sum(int(process.get("memoryMiB", 0) or 0) for process in vllm_processes)
    percent = round((used / total) * 100, 1) if total else None
    active[0]["gpuMemoryObservedMiB"] = used
    active[0]["gpuMemoryObservedPercent"] = percent
    active[0]["gpuMemoryPercent"] = percent
    active[0]["gpuMemorySource"] = "observed process memory"


def _gpu_memory_target_percent(runtime: dict[str, Any]) -> float | None:
    value = runtime.get("gpuMemoryUtilization")
    if value is None:
        value = _command_arg(runtime.get("command"), "--gpu-mem")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number * 100 if number <= 1 else number, 1)


def _command_arg(command: Any, flag: str) -> str | None:
    if not isinstance(command, list):
        return None
    try:
        index = command.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return str(command[index + 1])

def settings_status() -> dict[str, Any]:
    return {
        "projectPath": str(PROJECT_DIR),
        "recipePath": str(PROJECT_DIR / "recipes"),
        "defaultPortRange": f"{1024}-{65535}",
        "refreshIntervalSeconds": 5,
        "demoMode": False,
        "authenticationToken": "Configured",
        "healthCheckTimeoutSeconds": 1.5,
    }


def _tail_file(path: Path, lines: int) -> str:
    if not path or not path.exists():
        return ""
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _process_running(pid: Any) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DGX Spark vLLM dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"Control token: {CONTROL_TOKEN}")
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Parse and merge vLLM runtime telemetry for the dashboard."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.request import urlopen

from .runtime_state import utc_now


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MEMORY_PATTERNS = (
    ("modelMiB", re.compile(r"(?:loading model weights|model loading|model weights|model memory|weights).*?(\d+(?:\.\d+)?)\s*(GiB|GB|MiB|MB)", re.IGNORECASE)),
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


def has_new_memory_values(current: Any, previous: Any) -> bool:
    if not isinstance(current, dict):
        return False
    previous_values = previous if isinstance(previous, dict) else {}
    for key, value in current.items():
        if value is not None and previous_values.get(key) != value:
            return True
    return False


def runtime_token_metrics(runtime: dict[str, Any]) -> dict[str, Any]:
    return fetch_vllm_prometheus_token_metrics(runtime) or unavailable_token_metrics()


def unavailable_token_metrics() -> dict[str, Any]:
    return {
        "source": "unavailable",
        "promptTokensTotal": None,
        "generationTokensTotal": None,
        "tokensTotal": None,
        "requestCount": None,
        "sampledAt": None,
        "currentGeneratedTokensPerSecond": None,
        "lastActiveGeneratedTokensPerSecond": None,
        "peakGeneratedTokensPerSecond": None,
        "timePerOutputTokenMs": None,
        "interTokenLatencyMs": None,
        "endToEndLatencySeconds": None,
        "kvCacheUsagePercent": None,
        "prefixCacheHitPercent": None,
    }


def fetch_vllm_prometheus_token_metrics(runtime: dict[str, Any]) -> dict[str, Any] | None:
    if runtime.get("status") not in {"Ready", "Running"}:
        return None
    port = runtime.get("port")
    if not str(port).isdigit():
        return None
    try:
        with urlopen(f"http://127.0.0.1:{port}/metrics", timeout=0.8) as response:
            text = response.read(1_000_000).decode("utf-8", errors="replace")
    except OSError:
        return None
    metrics = parse_prometheus_token_metrics(text)
    if metrics:
        metrics["sampledAt"] = utc_now()
    return metrics


def parse_prometheus_token_metrics(text: str) -> dict[str, Any] | None:
    prompt_total = 0.0
    generation_total = 0.0
    request_count = 0.0
    time_per_output_token_seconds = 0.0
    time_per_output_token_count = 0.0
    inter_token_latency_seconds = 0.0
    inter_token_latency_count = 0.0
    e2e_latency_seconds = 0.0
    e2e_latency_count = 0.0
    kv_cache_usage = None
    prefix_cache_queries = 0.0
    prefix_cache_hits = 0.0
    found = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        name = parts[0].split("{", 1)[0].replace(":", "_")
        try:
            value = float(parts[1])
        except ValueError:
            continue
        if name.endswith("prompt_tokens_total"):
            prompt_total += value
            found = True
        elif name.endswith("generation_tokens_total"):
            generation_total += value
            found = True
        elif name.endswith("request_success_total"):
            request_count += value
        elif name.endswith("request_time_per_output_token_seconds_sum"):
            time_per_output_token_seconds += value
        elif name.endswith("request_time_per_output_token_seconds_count"):
            time_per_output_token_count += value
        elif name.endswith("inter_token_latency_seconds_sum"):
            inter_token_latency_seconds += value
        elif name.endswith("inter_token_latency_seconds_count"):
            inter_token_latency_count += value
        elif name.endswith("e2e_request_latency_seconds_sum"):
            e2e_latency_seconds += value
        elif name.endswith("e2e_request_latency_seconds_count"):
            e2e_latency_count += value
        elif name.endswith("kv_cache_usage_perc"):
            kv_cache_usage = max(kv_cache_usage or 0.0, value)
        elif name.endswith("prefix_cache_queries_total"):
            prefix_cache_queries += value
        elif name.endswith("prefix_cache_hits_total"):
            prefix_cache_hits += value
    if not found:
        return None
    prompt = int(prompt_total)
    generation = int(generation_total)
    return {
        "source": "prometheus",
        "promptTokensTotal": prompt,
        "generationTokensTotal": generation,
        "tokensTotal": prompt + generation,
        "requestCount": int(request_count) if request_count else None,
        "timePerOutputTokenMs": _average_seconds_to_ms(time_per_output_token_seconds, time_per_output_token_count),
        "interTokenLatencyMs": _average_seconds_to_ms(inter_token_latency_seconds, inter_token_latency_count),
        "endToEndLatencySeconds": _average_seconds(e2e_latency_seconds, e2e_latency_count),
        "kvCacheUsagePercent": round(kv_cache_usage * 100, 1) if kv_cache_usage is not None else None,
        "prefixCacheHitPercent": round((prefix_cache_hits / prefix_cache_queries) * 100, 1) if prefix_cache_queries > 0 else None,
    }


def merge_token_metrics(stored: Any, parsed: dict[str, Any]) -> dict[str, Any]:
    if token_metrics_available(parsed):
        return _with_observed_token_rates(stored, parsed)
    return stored if isinstance(stored, dict) else parsed


def has_new_token_metrics(current: Any, previous: Any) -> bool:
    return isinstance(current, dict) and token_metrics_available(current) and current != previous


def token_metrics_available(metrics: Any) -> bool:
    if not isinstance(metrics, dict):
        return False
    if metrics.get("source") == "prometheus":
        return True
    return any(metrics.get(key) is not None for key in ("promptTokensTotal", "generationTokensTotal", "tokensTotal"))


def _with_observed_token_rates(stored: Any, current: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    previous = stored if isinstance(stored, dict) else {}
    previous_sampled_at = _parse_iso_datetime(previous.get("sampledAt"))
    current_sampled_at = _parse_iso_datetime(current.get("sampledAt"))
    previous_generation = previous.get("generationTokensTotal")
    current_generation = current.get("generationTokensTotal")
    current_rate = None
    if (
        previous_sampled_at
        and current_sampled_at
        and isinstance(previous_generation, int | float)
        and isinstance(current_generation, int | float)
    ):
        elapsed = (current_sampled_at - previous_sampled_at).total_seconds()
        delta = current_generation - previous_generation
        if elapsed > 0 and delta >= 0:
            current_rate = round(delta / elapsed, 1)
    previous_last_active = previous.get("lastActiveGeneratedTokensPerSecond")
    previous_peak = previous.get("peakGeneratedTokensPerSecond")
    merged["currentGeneratedTokensPerSecond"] = current_rate
    merged["lastActiveGeneratedTokensPerSecond"] = current_rate if current_rate and current_rate > 0 else previous_last_active
    peaks = [value for value in (previous_peak, current_rate) if isinstance(value, int | float)]
    merged["peakGeneratedTokensPerSecond"] = round(max(peaks), 1) if peaks else None
    return merged


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _average_seconds_to_ms(seconds_sum: float, count: float) -> float | None:
    average = _average_seconds(seconds_sum, count)
    return round(average * 1000, 1) if average is not None else None


def _average_seconds(seconds_sum: float, count: float) -> float | None:
    return round(seconds_sum / count, 3) if seconds_sum > 0 and count > 0 else None

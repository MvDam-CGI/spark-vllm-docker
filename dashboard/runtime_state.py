"""Persist dashboard-launched runtime metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def upsert(self, runtime: dict[str, Any]) -> None:
        runtimes = [item for item in self.list() if item.get("id") != runtime.get("id")]
        runtimes.append(runtime)
        self._write(runtimes)

    def get(self, runtime_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item.get("id") == runtime_id), None)

    def update_status(self, runtime_id: str, status: str) -> None:
        runtimes = self.list()
        for runtime in runtimes:
            if runtime.get("id") == runtime_id:
                runtime["status"] = status
                runtime["updatedAt"] = utc_now()
                break
        self._write(runtimes)

    def _write(self, runtimes: list[dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(runtimes, indent=2), encoding="utf-8")
        tmp.replace(self.path)

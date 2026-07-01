"""Read and normalize vLLM recipe YAML files for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Recipe:
    slug: str
    name: str
    description: str
    model: str | None
    container: str
    defaults: dict[str, Any]
    mods: list[str]
    env: dict[str, str]
    solo_only: bool
    cluster_only: bool

    @property
    def default_port(self) -> int:
        return int(self.defaults.get("port", 8000))

    @property
    def default_host(self) -> str:
        return str(self.defaults.get("host", "0.0.0.0"))

    @property
    def default_gpu_memory_utilization(self) -> float:
        return float(self.defaults.get("gpu_memory_utilization", 0.7))

    @property
    def default_max_model_len(self) -> int:
        return int(self.defaults.get("max_model_len", 2048))

    def to_api(self) -> dict[str, Any]:
        support = "Solo" if self.solo_only else "Cluster" if self.cluster_only else "Solo and Cluster"
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "container": self.container,
            "defaults": self.defaults,
            "mods": self.mods,
            "envKeys": sorted(self.env.keys()),
            "soloOnly": self.solo_only,
            "clusterOnly": self.cluster_only,
            "support": support,
            "defaultPort": self.default_port,
            "defaultHost": self.default_host,
            "defaultGpuMemoryUtilization": self.default_gpu_memory_utilization,
            "defaultMaxModelLen": self.default_max_model_len,
        }


def load_recipes(project_dir: Path) -> list[Recipe]:
    recipes_dir = project_dir / "recipes"
    recipes: list[Recipe] = []
    for path in sorted(recipes_dir.glob("*.yaml")):
        recipes.append(load_recipe(path))
    return recipes


def load_recipe(path: Path) -> Recipe:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    required = ("name", "recipe_version", "container", "command")
    missing = [field for field in required if field not in data]
    if missing:
        raise ValueError(f"{path.name} is missing: {', '.join(missing)}")

    return Recipe(
        slug=path.stem,
        name=str(data["name"]),
        description=str(data.get("description", "")),
        model=data.get("model"),
        container=str(data["container"]),
        defaults=dict(data.get("defaults") or {}),
        mods=list(data.get("mods") or []),
        env={str(key): str(value) for key, value in dict(data.get("env") or {}).items()},
        solo_only=bool(data.get("solo_only", False)),
        cluster_only=bool(data.get("cluster_only", False)),
    )


def recipe_map(project_dir: Path) -> dict[str, Recipe]:
    return {recipe.slug: recipe for recipe in load_recipes(project_dir)}

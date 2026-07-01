from pathlib import Path

import pytest

from dashboard.commands import build_launch_plan
from dashboard.recipes import load_recipe
from dashboard.system_status import system_status


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
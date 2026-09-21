from pathlib import Path

import yaml

from scripts.router_federation import select, validate


CONFIG = yaml.safe_load((Path(__file__).parents[1] / "config/router-federation.yaml").read_text())


def test_catalog_is_valid_and_classifies_distinct_layers():
    result = validate(CONFIG)
    assert result["valid"] is True
    assert result["adapters"] == 18
    assert "gateway" in result["kinds"]
    assert "prompt_compressor" in result["kinds"]
    assert "kv_cache" in result["kinds"]


def test_only_enabled_installed_healthy_gateways_are_selected():
    benchmarks = {
        "litellm": {"healthy": True, "quality": 0.9, "latency_ms": 100, "cost_per_1k": 0, "privacy": 1, "fallback_success": 0.9, "gpu_efficiency": 0.7},
        "bifrost": {"healthy": True, "quality": 1, "latency_ms": 1, "cost_per_1k": 0, "privacy": 1, "fallback_success": 1, "gpu_efficiency": 1},
    }
    result = select(CONFIG, benchmarks, {"openai_api"})
    assert result["selected"]["adapter"] == "litellm"
    assert result["fallbacks"] == []


def test_required_capability_and_health_fail_closed():
    assert select(CONFIG, {"litellm": {"healthy": False}}, {"openai_api"})["decision"] == "blocked"
    assert select(CONFIG, {"litellm": {"healthy": True}}, {"anthropic_api"})["decision"] == "blocked"

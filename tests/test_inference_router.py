from pathlib import Path

import yaml

from scripts.inference_router import evaluate, route


CONFIG = yaml.safe_load((Path(__file__).parents[1] / "config/inference-control-tower.yaml").read_text())


def test_cache_short_circuits_all_inference():
    result = route(CONFIG, {"query": "hello", "exact_cache_hit": True}, {})
    assert result == {"decision": "cache", "provider": "exact_cache", "stages": ["exact_cache_hit"]}


def test_current_host_routes_to_direct_local_ollama():
    availability = {"direct_ollama": {"healthy": True, "models": ["qwen3:1.7b"]}}
    result = route(CONFIG, {"query": "answer briefly", "kind": "prose"}, availability)
    assert result["provider"] == "direct_ollama"
    assert result["model"] == "qwen3:1.7b"
    assert result["output_limit_tokens"] == 128


def test_free_and_paid_providers_fail_closed_by_default():
    availability = {"free_cloud": {"healthy": True, "quota_available": True}, "paid_cloud": {"healthy": True}}
    result = route(CONFIG, {"query": "security architecture", "allow_paid": True}, availability)
    assert result["decision"] == "blocked"


def test_quality_accept_escalate_and_reject():
    plan = {"provider": "direct_ollama"}
    assert evaluate(CONFIG, plan, 0.9, 0)["action"] == "accept"
    assert evaluate(CONFIG, plan, 0.5, 0)["action"] == "escalate"
    assert evaluate(CONFIG, plan, 0.5, 1)["action"] == "reject"

#!/usr/bin/env python3
"""Auditable router-of-routers plan for local, free, and paid inference."""

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

try:
    from token_router import choose_route, estimate_tokens, output_limit
except ModuleNotFoundError:
    from scripts.token_router import choose_route, estimate_tokens, output_limit


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/inference-control-tower.yaml"


def route(config: dict[str, Any], request: dict[str, Any], availability: dict[str, Any]) -> dict[str, Any]:
    query = request.get("query", ""); kind = request.get("kind", "prose")
    context_tokens = int(request.get("context_tokens", estimate_tokens(request.get("context", ""))))
    stages = []
    if request.get("exact_cache_hit"):
        return {"decision": "cache", "provider": "exact_cache", "stages": ["exact_cache_hit"]}
    stages.append("exact_cache_miss")
    if request.get("semantic_cache_hit"):
        return {"decision": "cache", "provider": "semantic_cache", "stages": stages + ["semantic_cache_hit"]}
    stages.extend(["semantic_cache_miss", "context_optimization"])
    tier = choose_route(query, context_tokens, kind); stages.extend(["task_router", "agent_router", "model_router"])
    model = config["models"][tier]["local"]

    candidates = []
    pair = config["local"]["nvidia_pair"]
    if pair["enabled"] and availability.get("pair", {}).get("healthy") and model in availability["pair"].get("models", []):
        candidates.append(("pair", pair["endpoint"], model))
    direct = config["local"]["direct_ollama"]
    if direct["enabled"] and availability.get("direct_ollama", {}).get("healthy") and model in availability["direct_ollama"].get("models", []):
        candidates.append(("direct_ollama", direct["endpoint"], model))
    free = config["free_cloud"]
    if free["enabled"] and availability.get("free_cloud", {}).get("healthy") and availability["free_cloud"].get("quota_available"):
        candidates.append(("free_cloud", free["endpoint"], availability["free_cloud"].get("model", tier)))
    paid = config["paid_cloud"]
    if paid["enabled"] and request.get("allow_paid") and availability.get("paid_cloud", {}).get("healthy"):
        candidates.append(("paid_cloud", paid["endpoint"], availability["paid_cloud"].get("model", tier)))
    order = {name: index for index, name in enumerate(config["fallback_order"])}
    candidates.sort(key=lambda item: order[item[0]])
    if not candidates:
        return {"decision": "blocked", "reason": "no_eligible_provider", "tier": tier, "stages": stages + ["provider_router"]}
    provider, endpoint, selected_model = candidates[0]
    return {"decision": "inference", "provider": provider, "endpoint": endpoint, "model": selected_model,
            "tier": tier, "output_limit_tokens": output_limit(query, tier), "fallbacks": [item[0] for item in candidates[1:]],
            "stages": stages + ["provider_router", "evaluator_required"]}


def evaluate(config: dict[str, Any], plan: dict[str, Any], score: float, escalations: int) -> dict[str, Any]:
    if score >= config["quality"]["minimum_score"]:
        return {"action": "accept", "cache": True, "collective_memory": "verified_only"}
    if escalations < config["quality"]["maximum_escalations"]:
        return {"action": "escalate", "reason": "quality_below_threshold", "exclude_provider": plan.get("provider")}
    return {"action": "reject", "reason": "quality_failed_after_escalation"}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan"); plan.add_argument("request_json"); plan.add_argument("availability_json")
    check = sub.add_parser("evaluate"); check.add_argument("plan_json"); check.add_argument("score", type=float); check.add_argument("--escalations", type=int, default=0)
    args = parser.parse_args(); config = yaml.safe_load(args.config.read_text())
    result = route(config, json.loads(args.request_json), json.loads(args.availability_json)) if args.command == "plan" else evaluate(config, json.loads(args.plan_json), args.score, args.escalations)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__": main()

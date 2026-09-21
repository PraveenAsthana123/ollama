#!/usr/bin/env python3
"""Validate and rank router adapters using measured benchmark evidence."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/router-federation.yaml"
SELECTABLE = {"gateway", "compatibility_gateway", "cloud_aggregator"}


def validate(config: dict[str, Any]) -> dict[str, Any]:
    errors = []
    for name, adapter in config.get("adapters", {}).items():
        if adapter.get("enabled") and not adapter.get("installed"):
            errors.append(f"{name}: enabled but not installed")
        if adapter.get("enabled") and adapter.get("kind") in SELECTABLE and not adapter.get("endpoint"):
            errors.append(f"{name}: enabled gateway has no endpoint")
    total = len(config.get("adapters", {}))
    kinds = sorted({adapter["kind"] for adapter in config.get("adapters", {}).values()})
    return {"valid": not errors, "errors": errors, "adapters": total, "kinds": kinds}


def eligible(config: dict[str, Any], benchmarks: dict[str, Any], required: set[str]) -> list[tuple[str, dict, dict]]:
    result = []
    now = time.time()
    for name, adapter in config["adapters"].items():
        measurement = benchmarks.get(name, {})
        if adapter["kind"] not in SELECTABLE or not adapter.get("enabled") or not adapter.get("installed"): continue
        if not required <= set(adapter.get("capabilities", [])): continue
        if not measurement.get("healthy"): continue
        if float(measurement.get("circuit_open_until", 0)) > now: continue
        result.append((name, adapter, measurement))
    return result


def score(config: dict[str, Any], measurement: dict[str, Any]) -> float:
    weights = config["selection_weights"]
    values = {
        "quality": float(measurement.get("quality", 0)),
        "latency": 1 / (1 + float(measurement.get("latency_ms", 1)) / 1000),
        "cost": 1 / (1 + float(measurement.get("cost_per_1k", 0)) * 100),
        "privacy": float(measurement.get("privacy", 0)),
        "fallback_success": float(measurement.get("fallback_success", 0)),
        "gpu_efficiency": float(measurement.get("gpu_efficiency", 0)),
    }
    return round(sum(values[key] * weights[key] for key in weights), 6)


def select(config: dict[str, Any], benchmarks: dict[str, Any], required: set[str]) -> dict[str, Any]:
    candidates = [{"adapter": name, "endpoint": adapter.get("endpoint"), "score": score(config, measurement)}
                  for name, adapter, measurement in eligible(config, benchmarks, required)]
    candidates.sort(key=lambda item: (-item["score"], item["adapter"]))
    if not candidates: return {"decision": "blocked", "reason": "no_eligible_router", "candidates": []}
    return {"decision": "route", "selected": candidates[0], "fallbacks": candidates[1:]}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True); sub.add_parser("validate")
    choose = sub.add_parser("select"); choose.add_argument("benchmarks_json"); choose.add_argument("--require", default="openai_api")
    listing = sub.add_parser("list"); listing.add_argument("--kind")
    args = parser.parse_args(); config = yaml.safe_load(args.config.read_text())
    if args.command == "validate": result = validate(config)
    elif args.command == "select": result = select(config, json.loads(args.benchmarks_json), {item for item in args.require.split(",") if item})
    else:
        result = [{"name": name, **adapter} for name, adapter in config["adapters"].items() if not args.kind or adapter["kind"] == args.kind]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__": main()

#!/usr/bin/env python3
"""Local AgentOps replay, incident analysis, and CI quality gates."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import yaml

try:
    from agent_monitor import EventStore, snapshot
except ModuleNotFoundError:
    from scripts.agent_monitor import EventStore, snapshot


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/agentops.yaml"


def replay(events: list[dict[str, Any]], session_id: str) -> list[dict[str, Any]]:
    selected = [event for event in events if event.get("session_id") == session_id]
    return sorted(selected, key=lambda event: float(event.get("timestamp", 0)))


def incidents(events: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    statuses = set(config["incidents"]["statuses"]); categories = set(config["incidents"]["categories"])
    return [event for event in events if event.get("status") in statuses and event.get("category") in categories]


def gate(events: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    policy = config["quality_gate"]; fleet = snapshot(events)
    terminal = [event for event in events if event.get("category") == "task" and event.get("status") in {"completed", "failed", "blocked"}]
    successful = sum(event["status"] == "completed" for event in terminal)
    success_rate = successful / len(terminal) if terminal else 0.0
    quality = [float(event.get("quality_score", 0)) for event in events if event.get("category") == "quality"]
    grounding = [float(event.get("grounding_score", 0)) for event in events if event.get("category") == "quality"]
    security = [event for event in events if event.get("category") == "security"]
    total_cost = sum(float(event.get("cost_usd", 0)) for event in events)
    metrics = {
        "success_rate": round(success_rate, 4),
        "quality_score": round(sum(quality) / len(quality), 4) if quality else None,
        "grounding_score": round(sum(grounding) / len(grounding), 4) if grounding else None,
        "error_rate": fleet["error_rate"], "p95_latency_ms": fleet["latency_ms"]["p95"],
        "cost_per_success_usd": round(total_cost / successful, 6) if successful else None,
        "policy_violations": fleet["policy_violations"],
    }
    failures = []
    checks = (
        (metrics["success_rate"] >= policy["minimum_success_rate"], "success_rate"),
        (metrics["error_rate"] <= policy["maximum_error_rate"], "error_rate"),
        (metrics["p95_latency_ms"] <= policy["maximum_p95_latency_ms"], "p95_latency"),
        (metrics["policy_violations"] <= policy["maximum_policy_violations"], "policy_violations"),
    )
    failures.extend(name for passed, name in checks if not passed)
    if policy["require_quality_events"] and not quality: failures.append("quality_evidence_missing")
    elif quality and metrics["quality_score"] < policy["minimum_quality_score"]: failures.append("quality_score")
    if quality and metrics["grounding_score"] < policy["minimum_grounding_score"]: failures.append("grounding_score")
    if policy["require_security_events"] and not security: failures.append("security_evidence_missing")
    if metrics["cost_per_success_usd"] is not None and metrics["cost_per_success_usd"] > policy["maximum_cost_per_success_usd"]:
        failures.append("cost_per_success")
    return {"passed": not failures, "failures": failures, "metrics": metrics,
            "sessions": len({event.get("session_id") for event in events if event.get("session_id")})}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--events", type=Path, default=Path.home()/".local/state/ollama-control-tower/monitor/events.jsonl")
    parser.add_argument("--since-seconds", type=int, default=86400)
    sub = parser.add_subparsers(dest="command", required=True)
    play = sub.add_parser("replay"); play.add_argument("session_id")
    sub.add_parser("incidents"); quality = sub.add_parser("gate"); quality.add_argument("--strict", action="store_true")
    args = parser.parse_args(); config = yaml.safe_load(args.config.read_text())
    events = EventStore(args.events).read(time.time() - args.since_seconds)
    if args.command == "replay": result = replay(events, args.session_id)
    elif args.command == "incidents": result = incidents(events, config)
    else:
        result = gate(events, config)
        if args.strict and not result["passed"]:
            print(json.dumps(result, indent=2, sort_keys=True)); raise SystemExit(1)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__": main()

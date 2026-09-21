#!/usr/bin/env python3
"""Aggregate token efficiency and recommend automatic Token Tower reactions."""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from agent_monitor import EventStore
except ModuleNotFoundError:  # Imported as scripts.token_metrics in tests.
    from scripts.agent_monitor import EventStore


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {name: defaultdict(int) for name in ("agent", "task", "tool", "mcp", "model")}
    total_input = total_output = cached = compressed = calls = hits = local = cloud = successes = 0
    cost = duplicate_weight = utilization_weight = 0.0
    for event in events:
        if event.get("category") not in {"tokens", "model", "mcp"}: continue
        calls += 1
        incoming = int(event.get("input_tokens", 0)); outgoing = int(event.get("output_tokens", 0))
        total = incoming + outgoing; total_input += incoming; total_output += outgoing
        cached += int(event.get("cached_tokens", 0)); compressed += int(event.get("compressed_tokens", 0))
        cost += float(event.get("cost_usd", 0)); hits += bool(event.get("cache_hit"))
        successes += event.get("status") == "completed"
        local += event.get("provider") in {"ollama", "local"}; cloud += event.get("provider") == "cloud"
        duplicate_weight += float(event.get("duplicate_context_ratio", 0)) * incoming
        utilization_weight += float(event.get("context_utilization", 0)) * incoming
        for group, key in (("agent", "agent_id"), ("task", "task_id"), ("tool", "tool"),
                           ("mcp", "mcp_server"), ("model", "model")):
            if event.get(key): groups[group][event[key]] += total
    return {
        "calls": calls, "input_tokens": total_input, "output_tokens": total_output,
        "cached_tokens": cached, "compressed_tokens": compressed,
        "tokens_by_agent": dict(groups["agent"]), "tokens_by_task": dict(groups["task"]),
        "tokens_by_tool": dict(groups["tool"]), "tokens_by_mcp": dict(groups["mcp"]),
        "tokens_by_model": dict(groups["model"]),
        "duplicate_context_ratio": round(duplicate_weight / total_input, 4) if total_input else 0,
        "context_utilization": round(utilization_weight / total_input, 4) if total_input else 0,
        "cache_hit_rate": round(hits / calls, 4) if calls else 0,
        "local_vs_cloud_ratio": {"local": local, "cloud": cloud},
        "cost_per_successful_task": round(cost / successes, 6) if successes else 0,
    }


def reaction(metrics: dict[str, Any]) -> list[str]:
    actions = []
    if metrics["duplicate_context_ratio"] >= 0.20: actions.append("deduplicate_and_prune")
    if metrics["context_utilization"] >= 0.80: actions.append("summarize_or_compress")
    if metrics["cache_hit_rate"] < 0.10 and metrics["calls"] >= 10: actions.append("enable_semantic_cache")
    if metrics["local_vs_cloud_ratio"]["cloud"] > metrics["local_vs_cloud_ratio"]["local"]: actions.append("route_easy_tasks_local")
    return actions or ["none"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=Path.home()/".local/state/ollama-control-tower/monitor/events.jsonl")
    parser.add_argument("--since-seconds", type=int, default=86400)
    args = parser.parse_args()
    events = EventStore(args.events).read(time.time() - args.since_seconds)
    result = aggregate(events); result["reactions"] = reaction(result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__": main()

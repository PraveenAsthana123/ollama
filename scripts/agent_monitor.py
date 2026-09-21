#!/usr/bin/env python3
"""Local, vendor-neutral monitoring event store and fleet snapshot."""

import argparse
import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any


CATEGORIES = {
    "health", "task", "supervisor", "a2a", "mcp", "model", "tokens",
    "cost", "performance", "memory", "quality", "security",
}
STATUSES = {"queued", "running", "completed", "failed", "blocked", "idle", "terminated"}
REDACT_KEYS = {"authorization", "cookie", "password", "secret", "token", "api_key"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.casefold() in REDACT_KEYS else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class EventStore:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        category = event.get("category")
        status = event.get("status")
        if category not in CATEGORIES:
            raise ValueError(f"unknown category: {category}")
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        if not event.get("agent_id") or not event.get("name"):
            raise ValueError("agent_id and name are required")
        clean = redact(event)
        clean.setdefault("timestamp", time.time())
        clean.setdefault("session_id", "")
        clean.setdefault("task_id", "")
        line = json.dumps(clean, separators=(",", ":"), sort_keys=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (line + "\n").encode())
        finally:
            os.close(descriptor)
        os.chmod(self.path, 0o600)
        return clean

    def read(self, since: float = 0) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                event = json.loads(line)
                if float(event.get("timestamp", 0)) >= since:
                    events.append(event)
        return events


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percent * len(ordered)) - 1)
    return round(ordered[index], 3)


def snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(event["status"] for event in events)
    categories = Counter(event["category"] for event in events)
    agents = Counter(event["agent_id"] for event in events)
    latencies = [float(event["latency_ms"]) for event in events if "latency_ms" in event]
    failures = sum(status in {"failed", "blocked"} for status in (e["status"] for e in events))
    return {
        "events": len(events),
        "agents": len(agents),
        "status": dict(statuses),
        "dimensions": dict(categories),
        "tokens": {
            "input": sum(int(e.get("input_tokens", 0)) for e in events),
            "output": sum(int(e.get("output_tokens", 0)) for e in events),
            "cached": sum(int(e.get("cached_tokens", 0)) for e in events),
            "compressed": sum(int(e.get("compressed_tokens", 0)) for e in events),
        },
        "cost_usd": round(sum(float(e.get("cost_usd", 0)) for e in events), 6),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "error_rate": round(failures / len(events), 4) if events else 0.0,
        "handoffs": sum(e["category"] == "a2a" for e in events),
        "tool_calls": sum(e["category"] == "mcp" for e in events),
        "policy_violations": sum(e["category"] == "security" and e["status"] == "blocked" for e in events),
    }


def alert_decision(summary: dict[str, Any]) -> dict[str, str]:
    if summary["policy_violations"]:
        return {"action": "kill", "reason": "security_policy_violation"}
    if summary["error_rate"] >= 0.25:
        return {"action": "pause", "reason": "error_rate_25_percent"}
    if summary["error_rate"] >= 0.10 or summary["latency_ms"]["p95"] >= 10000:
        return {"action": "warn", "reason": "health_threshold"}
    return {"action": "none", "reason": "healthy"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, default=Path.home() / ".local/state/ollama-control-tower/monitor/events.jsonl")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    record.add_argument("event_json")
    report = sub.add_parser("snapshot")
    report.add_argument("--since-seconds", type=int, default=86400)
    sub.add_parser("health")
    args = parser.parse_args()
    store = EventStore(args.events)
    if args.command == "record":
        result = store.append(json.loads(args.event_json))
    else:
        events = store.read(time.time() - args.since_seconds) if args.command == "snapshot" else store.read()
        result = snapshot(events)
        result["alert"] = alert_decision(result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only fleet view over Agent Control state and Monitoring events."""

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from agent_control import AgentState, budget_decision
    from agent_monitor import EventStore, percentile
except ModuleNotFoundError:
    from scripts.agent_control import AgentState, budget_decision
    from scripts.agent_monitor import EventStore, percentile


DEFAULT_AGENTS = Path.home() / ".local/state/ollama-control-tower/agents"
DEFAULT_EVENTS = Path.home() / ".local/state/ollama-control-tower/monitor/events.jsonl"


def fleet_snapshot(states: list[AgentState], events: list[dict[str, Any]], now: float,
                   stale_seconds: int = 300) -> dict[str, Any]:
    by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("agent_id"):
            by_agent[event["agent_id"]].append(event)
    children: dict[str, list[str]] = defaultdict(list)
    for state in states:
        if state.parent_agent_id:
            children[state.parent_agent_id].append(state.agent_id)
    rows = []
    for state in states:
        stream = by_agent[state.agent_id]
        failures = sum(event.get("status") in {"failed", "blocked"} for event in stream)
        latencies = [float(event["latency_ms"]) for event in stream if "latency_ms" in event]
        last_event = max((float(event.get("timestamp", 0)) for event in stream), default=0)
        last_seen = max(state.updated_at, state.last_progress_at, last_event)
        stalled = state.status in {"RUNNING", "STEPPING"} and now - last_seen > stale_seconds
        rows.append({
            "agent_id": state.agent_id, "parent_agent_id": state.parent_agent_id,
            "children": sorted(children[state.agent_id]), "session_id": state.session_id,
            "task": state.task, "worker": state.worker, "model": state.model,
            "status": state.status, "priority": state.priority, "trust": state.trust,
            "stalled": stalled, "seconds_since_seen": round(max(0, now - last_seen), 1),
            "tokens_used": state.tokens_used, "token_limit": state.token_limit,
            "cost_usd": state.cost_usd, "cost_limit_usd": state.cost_limit_usd,
            "steps": state.steps, "step_limit": state.step_limit,
            "budget": budget_decision(state), "event_count": len(stream),
            "failures": failures, "handoffs": sum(event.get("category") == "a2a" for event in stream),
            "p95_latency_ms": percentile(latencies, 0.95),
        })
    rows.sort(key=lambda row: (-row["priority"], row["agent_id"]))
    return {
        "agents": rows,
        "totals": {
            "agents": len(rows), "statuses": dict(Counter(row["status"] for row in rows)),
            "stalled": sum(row["stalled"] for row in rows),
            "tokens_used": sum(row["tokens_used"] for row in rows),
            "cost_usd": round(sum(row["cost_usd"] for row in rows), 6),
            "failures": sum(row["failures"] for row in rows),
            "handoffs": sum(row["handoffs"] for row in rows),
        },
    }


def load_states(root: Path) -> list[AgentState]:
    if not root.exists():
        return []
    states = []
    for path in root.glob("*.json"):
        # Only state files created with the agent-id filename policy are read.
        if path.is_symlink() or not all(char.isalnum() or char in "-_" for char in path.stem):
            continue
        states.append(AgentState(**json.loads(path.read_text())))
    return states


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents-dir", type=Path, default=DEFAULT_AGENTS)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--since-seconds", type=int, default=86400)
    parser.add_argument("--stale-seconds", type=int, default=300)
    args = parser.parse_args()
    now = time.time()
    events = EventStore(args.events).read(now - args.since_seconds)
    result = fleet_snapshot(load_states(args.agents_dir), events, now, args.stale_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

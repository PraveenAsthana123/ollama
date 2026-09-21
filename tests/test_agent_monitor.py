from scripts.agent_monitor import EventStore, alert_decision, snapshot


def test_event_store_redacts_and_uses_private_permissions(tmp_path):
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    stored = store.append({
        "agent_id": "sales-1", "category": "mcp", "name": "crm.lookup",
        "status": "completed", "metadata": {"api_key": "do-not-store"},
    })
    assert stored["metadata"]["api_key"] == "[REDACTED]"
    assert path.stat().st_mode & 0o777 == 0o600


def test_snapshot_covers_cost_tokens_latency_and_behavior():
    events = [
        {"agent_id": "a", "category": "model", "name": "call", "status": "completed",
         "input_tokens": 10, "output_tokens": 5, "cached_tokens": 4,
         "compressed_tokens": 3, "cost_usd": 0.02, "latency_ms": 100},
        {"agent_id": "a", "category": "mcp", "name": "sql", "status": "failed", "latency_ms": 500},
        {"agent_id": "b", "category": "a2a", "name": "handoff", "status": "completed", "latency_ms": 200},
    ]
    result = snapshot(events)
    assert result["agents"] == 2
    assert result["tokens"] == {"input": 10, "output": 5, "cached": 4, "compressed": 3}
    assert result["cost_usd"] == 0.02
    assert result["tool_calls"] == 1
    assert result["handoffs"] == 1
    assert result["latency_ms"] == {"p50": 200.0, "p95": 500.0, "p99": 500.0}


def test_alerts_escalate_warn_pause_kill():
    base = {"error_rate": 0.0, "latency_ms": {"p95": 0}, "policy_violations": 0}
    assert alert_decision(base)["action"] == "none"
    assert alert_decision({**base, "error_rate": 0.10})["action"] == "warn"
    assert alert_decision({**base, "error_rate": 0.25})["action"] == "pause"
    assert alert_decision({**base, "policy_violations": 1})["action"] == "kill"

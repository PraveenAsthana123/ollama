from pathlib import Path

import yaml

from scripts.agentops import gate, incidents, replay


CONFIG = yaml.safe_load((Path(__file__).parents[1] / "config/agentops.yaml").read_text())


def passing_events():
    return [
        {"timestamp": 2, "session_id": "s1", "agent_id": "a", "category": "task", "name": "task", "status": "completed", "latency_ms": 100, "cost_usd": 0.02},
        {"timestamp": 1, "session_id": "s1", "agent_id": "a", "category": "security", "name": "policy", "status": "completed"},
        {"timestamp": 3, "session_id": "s1", "agent_id": "a", "category": "quality", "name": "eval", "status": "completed", "quality_score": 0.9, "grounding_score": 0.85},
    ]


def test_replay_orders_correlated_session():
    result = replay(passing_events() + [{"timestamp": 0, "session_id": "other"}], "s1")
    assert [event["timestamp"] for event in result] == [1, 2, 3]


def test_release_gate_passes_with_quality_and_security_evidence():
    result = gate(passing_events(), CONFIG)
    assert result["passed"] is True
    assert result["metrics"]["success_rate"] == 1.0


def test_gate_and_incident_detection_fail_closed():
    events = [{"session_id": "s2", "agent_id": "a", "category": "task", "name": "task", "status": "failed", "latency_ms": 12000}]
    result = gate(events, CONFIG)
    assert result["passed"] is False
    assert "quality_evidence_missing" in result["failures"]
    assert incidents(events, CONFIG) == events

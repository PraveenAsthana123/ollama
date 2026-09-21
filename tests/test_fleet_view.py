from scripts.agent_control import AgentState, StateStore, control
from scripts.fleet_view import fleet_snapshot, load_states


def test_fleet_joins_hierarchy_budgets_and_events(tmp_path):
    store = StateStore(tmp_path)
    parent = AgentState("supervisor", status="RUNNING", priority=10, updated_at=100, last_progress_at=100)
    child = AgentState("coder", parent_agent_id="supervisor", session_id="s1", status="RUNNING",
                       tokens_used=85, token_limit=100, priority=7, updated_at=100, last_progress_at=100)
    store.save(parent); store.save(child)
    states = load_states(tmp_path)
    for state in states:
        state.updated_at = 100; state.last_progress_at = 100
    events = [{"agent_id": "coder", "category": "a2a", "status": "completed", "latency_ms": 250, "timestamp": 110},
              {"agent_id": "coder", "category": "mcp", "status": "failed", "latency_ms": 500, "timestamp": 120}]
    result = fleet_snapshot(states, events, now=500, stale_seconds=300)
    assert result["totals"]["stalled"] == 2
    assert result["totals"]["handoffs"] == 1
    assert result["agents"][0]["children"] == ["coder"]
    assert result["agents"][1]["budget"]["action"] == "warn"
    assert result["agents"][1]["p95_latency_ms"] == 500


def test_priority_control_is_bounded():
    state = AgentState("coder")
    assert control(state, "priority", "8")["status"] == "PAUSED"
    assert state.priority == 8
    try:
        control(state, "priority", "11")
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range priority accepted")

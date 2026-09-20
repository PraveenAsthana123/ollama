from scripts.agent_control import AgentState, StateStore, apply_event, budget_decision, control, tool_decision


def test_pause_resume_step_and_terminal_state():
    state = AgentState("coder", status="RUNNING")
    assert control(state, "pause", None)["status"] == "PAUSED"
    assert control(state, "step", None)["status"] == "STEPPING"
    apply_event(state, {"tool": "tests", "state": "passed"})
    assert state.status == "PAUSED"
    assert control(state, "kill", None)["status"] == "KILLED"


def test_budget_warn_degrade_and_block():
    state = AgentState("coder", status="RUNNING", token_limit=100)
    state.tokens_used = 80
    assert budget_decision(state)["action"] == "warn"
    state.tokens_used = 90
    assert budget_decision(state)["action"] == "degrade"
    state.tokens_used = 100
    assert budget_decision(state)["action"] == "block"


def test_repeated_event_auto_halts():
    state = AgentState("coder", status="RUNNING")
    for _ in range(3):
        result = apply_event(state, {"tool": "shell", "state": "same", "progress": False})
    assert result == {"action": "halt", "reason": "repeated_state_or_tool_call"}
    assert state.status == "HALTED"


def test_tool_and_mcp_policy():
    state = AgentState("coder", status="RUNNING")
    assert tool_decision(state, "git.push")["action"] == "review"
    assert tool_decision(state, "sandbox.disable")["action"] == "block"
    state.blocked_mcp.append("terminal")
    assert tool_decision(state, "shell.run", "terminal")["action"] == "block"


def test_atomic_state_round_trip(tmp_path):
    store = StateStore(tmp_path)
    state = AgentState("security-agent-07", task="Scan API", status="RUNNING")
    store.save(state)
    loaded = store.load(state.agent_id)
    assert loaded.task == "Scan API"
    assert (tmp_path / "security-agent-07.json").stat().st_mode & 0o777 == 0o600

from pathlib import Path

import pytest

from scripts.supervisor import PlanStore, create_plan, load_config, ready_tasks, report, validate_plan


CONFIG = load_config(Path(__file__).parents[1] / "config/supervisor-tower.yaml")


def tasks():
    return [
        {"id": "arch", "agent": "Architect Agent", "instruction": "design"},
        {"id": "code", "agent": "Developer Agent", "instruction": "build", "depends_on": ["arch"]},
        {"id": "test", "agent": "QA Agent", "instruction": "test", "depends_on": ["code"]},
    ]


def test_dependency_scheduler_and_review_gate(tmp_path):
    plan = create_plan(CONFIG, "ship feature", tasks())
    assert [item["id"] for item in ready_tasks(CONFIG, plan)] == ["arch"]
    report(CONFIG, plan, "arch", {"success": True, "output": {"design": "v1"}})
    assert [item["id"] for item in ready_tasks(CONFIG, plan)] == ["code"]
    report(CONFIG, plan, "code", {"success": True, "output": {"commit": "abc"}})
    ready_tasks(CONFIG, plan)
    report(CONFIG, plan, "test", {"success": True, "output": {"tests": "passed"}})
    assert plan["status"] == "review"
    assert plan["blackboard"]["code"]["commit"] == "abc"
    store = PlanStore(tmp_path); store.save(plan)
    assert store.path(plan["plan_id"]).stat().st_mode & 0o777 == 0o600


def test_cycle_and_unknown_agent_are_rejected():
    cyclic = [
        {"id": "a", "agent": "Developer Agent", "depends_on": ["b"]},
        {"id": "b", "agent": "QA Agent", "depends_on": ["a"]},
    ]
    with pytest.raises(ValueError, match="cycle"):
        validate_plan(CONFIG, cyclic)
    with pytest.raises(ValueError, match="unroutable"):
        validate_plan(CONFIG, [{"id": "x", "agent": "Unknown Agent"}])


def test_retry_no_progress_and_budget_controls():
    plan = create_plan(CONFIG, "bounded", [{"id": "x", "agent": "Developer Agent"}])
    for attempt in range(3):
        ready_tasks(CONFIG, plan)
        result = report(CONFIG, plan, "x", {"success": False})
    assert result["plan_status"] == "failed"
    budget = create_plan(CONFIG, "cost", [{"id": "x", "agent": "Developer Agent"}])
    ready_tasks(CONFIG, budget)
    report(CONFIG, budget, "x", {"success": True, "cost_usd": 2.0})
    assert budget["status"] == "blocked"


def test_human_approval_and_timeout_gates():
    gated = create_plan(CONFIG, "deploy", [{"id": "deploy", "agent": "DevOps Agent", "approval": "production_deployment"}])
    assert ready_tasks(CONFIG, gated) == []
    assert gated["status"] == "awaiting_approval"
    gated["approvals"]["production_deployment"] = "approved"
    assert [task["id"] for task in ready_tasks(CONFIG, gated)] == ["deploy"]
    timed = create_plan(CONFIG, "old", [{"id": "x", "agent": "Developer Agent"}])
    timed["created_at"] -= CONFIG["limits"]["timeout_seconds"] + 1
    assert ready_tasks(CONFIG, timed) == []
    assert timed["status"] == "timed_out"

from pathlib import Path

from scripts.business_registry import load_registry, resolved_agents, validate_registry


REGISTRY = Path(__file__).parents[1] / "config/business-agent-registry.yaml"


def test_registry_is_complete_and_resolvable():
    registry = load_registry(REGISTRY)
    summary = validate_registry(registry)
    assert summary["domains"] == 22
    assert summary["role_assignments"] >= 80
    assert summary["supervisors"] == 5


def test_every_agent_resolves_five_classifications():
    agents = resolved_agents(load_registry(REGISTRY))
    for agent in agents:
        assert agent["domain"]
        assert agent["department"]
        assert agent["role"]
        assert agent["skills"]
        assert agent["tools"]


def test_regulated_workflow_has_human_gate():
    registry = load_registry(REGISTRY)
    loan = registry["workflows"]["loan_processing"]
    assert loan["chain"][:4] == ["Lending Agent", "KYC Agent", "AML Agent", "Fraud Agent"]
    assert loan["approval"] in registry["control_tower"]["require_human_approval_for"]

from pathlib import Path

from scripts.platform_audit import ROOT, audit, load


CONFIG = ROOT / "config/agentic-engineering-lifecycle.yaml"


def test_all_25_stages_have_honest_evidence_status():
    result = audit(load(CONFIG))
    assert result["valid"] is True
    assert len(result["stages"]) == 25
    assert result["counts"] == {"implemented": 18, "contract": 4, "planned": 2, "external": 1}


def test_audit_detects_missing_implemented_evidence(tmp_path):
    result = audit(load(CONFIG), tmp_path)
    assert result["valid"] is False
    assert any("missing evidence" in error for error in result["errors"])


def test_production_gaps_remain_explicit():
    result = audit(load(CONFIG))
    assert "runtime_adapters" in result["production_gates_open"]
    assert "continuous_evaluation" in result["production_gates_open"]

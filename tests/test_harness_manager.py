from pathlib import Path

from scripts.harness_manager import RunStore, complete, create_run, load, resolve, validate


CONFIG = Path(__file__).parents[1] / "config/harness-profiles.yaml"


def test_profiles_validate_and_keep_security_read_only():
    config = load(CONFIG)
    assert validate(config) == {"valid": True, "profiles": 5}
    security = resolve(config, "security")
    assert "filesystem.read" in security["tools"]
    assert "filesystem.write" not in security["tools"]
    assert security["network"] == "deny"


def test_production_requires_approval_and_rollback_evidence():
    production = resolve(load(CONFIG), "production")
    assert "production_deployment" in production["approvals"]
    assert "rollback_plan" in production["require_evidence"]


def test_run_is_private_and_evidence_gated(tmp_path):
    config = load(CONFIG)
    run = create_run(config, "coding", "coder-1", "fix parser")
    store = RunStore(tmp_path)
    store.save(run)
    assert store.path(run["run_id"]).stat().st_mode & 0o777 == 0o600
    rejected = complete(run, {"change_summary": "fixed"})
    assert rejected["accepted"] is False
    evidence = {key: "present" for key in run["policy"]["require_evidence"]}
    accepted = complete(run, evidence)
    assert accepted["accepted"] is True

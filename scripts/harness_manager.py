#!/usr/bin/env python3
"""Resolve harness profiles and manage evidence-gated agent runs."""

import argparse
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/harness-profiles.yaml"
TERMINAL = {"completed", "failed", "cancelled"}


def load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("harness configuration must be a mapping")
    return data


def resolve(config: dict[str, Any], profile: str) -> dict[str, Any]:
    if profile not in config.get("profiles", {}):
        raise ValueError(f"unknown harness profile: {profile}")
    result = dict(config["defaults"])
    result.update(config["profiles"][profile])
    result["profile"] = profile
    forbidden = set(config.get("forbidden_tools", []))
    overlap = forbidden.intersection(result.get("tools", []))
    if overlap:
        raise ValueError(f"profile grants forbidden tools: {sorted(overlap)}")
    return result


def validate(config: dict[str, Any]) -> dict[str, Any]:
    required = {"isolation", "network", "token_limit", "step_limit", "timeout_seconds",
                "retries", "require_evidence", "instructions", "memory", "mcp", "tools", "approvals"}
    missing = required - set(config.get("defaults", {}))
    if missing:
        raise ValueError(f"defaults missing: {sorted(missing)}")
    for name in config.get("profiles", {}):
        resolved = resolve(config, name)
        if resolved["isolation"] not in {"worktree", "container", "sandbox"}:
            raise ValueError(f"{name}: invalid isolation")
        if resolved["network"] not in {"deny", "review", "allow"}:
            raise ValueError(f"{name}: invalid network policy")
    return {"valid": True, "profiles": len(config.get("profiles", {}))}


class RunStore:
    def __init__(self, root: Path):
        self.root = root.expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, run_id: str) -> Path:
        if not run_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in run_id):
            raise ValueError("invalid run_id")
        return self.root / f"{run_id}.json"

    def save(self, run: dict[str, Any]) -> None:
        run["updated_at"] = time.time()
        descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix=".run-", text=True)
        try:
            with os.fdopen(descriptor, "w") as output:
                json.dump(run, output, indent=2, sort_keys=True)
                output.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path(run["run_id"]))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, run_id: str) -> dict[str, Any]:
        return json.loads(self.path(run_id).read_text())


def create_run(config: dict[str, Any], profile: str, agent_id: str, task: str) -> dict[str, Any]:
    policy = resolve(config, profile)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    workspace = str(Path(config["workspace_root"]).expanduser() / run_id)
    return {"run_id": run_id, "agent_id": agent_id, "task": task, "status": "created",
            "workspace": workspace, "policy": policy, "checkpoints": [], "evidence": {},
            "created_at": time.time(), "updated_at": time.time()}


def complete(run: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    if run["status"] in TERMINAL:
        raise ValueError(f"run already terminal: {run['status']}")
    required = set(run["policy"]["require_evidence"])
    missing = sorted(key for key in required if not evidence.get(key))
    run["evidence"] = evidence
    if missing:
        run["status"] = "verification_failed"
        return {"accepted": False, "missing_evidence": missing}
    run["status"] = "completed"
    return {"accepted": True, "missing_evidence": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    show = sub.add_parser("resolve"); show.add_argument("profile")
    create = sub.add_parser("create"); create.add_argument("profile"); create.add_argument("agent_id"); create.add_argument("task")
    status = sub.add_parser("status"); status.add_argument("run_id")
    checkpoint = sub.add_parser("checkpoint"); checkpoint.add_argument("run_id"); checkpoint.add_argument("evidence_json")
    finish = sub.add_parser("complete"); finish.add_argument("run_id"); finish.add_argument("evidence_json")
    args = parser.parse_args()
    config = load(args.config)
    validate(config)
    state_root = args.state_dir or Path(config["run_state_root"])
    store = RunStore(state_root)
    if args.command == "validate": result = validate(config)
    elif args.command == "resolve": result = resolve(config, args.profile)
    elif args.command == "create":
        run = create_run(config, args.profile, args.agent_id, args.task); store.save(run); result = run
    else:
        run = store.load(args.run_id)
        if args.command == "status": result = run
        elif args.command == "checkpoint":
            run["checkpoints"].append(json.loads(args.evidence_json)); store.save(run); result = run
        else:
            result = complete(run, json.loads(args.evidence_json)); store.save(run)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

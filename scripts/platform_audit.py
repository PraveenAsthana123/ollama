#!/usr/bin/env python3
"""Evidence-based audit of the Agentic Engineering lifecycle."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config/agentic-engineering-lifecycle.yaml"


def load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def audit(config: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    allowed = set(config.get("statuses", []))
    stages = config.get("stages", [])
    errors, rows = [], []
    ids = [stage.get("id") for stage in stages]
    if ids != list(range(1, 26)):
        errors.append("stage IDs must be the ordered range 1..25")
    for stage in stages:
        status = stage.get("status")
        if status not in allowed:
            errors.append(f"stage {stage.get('id')}: invalid status {status}")
        missing = [path for path in stage.get("evidence", []) if not (root / path).exists()]
        if status == "implemented" and not stage.get("evidence"):
            errors.append(f"stage {stage.get('id')}: implemented without evidence")
        if missing:
            errors.append(f"stage {stage.get('id')}: missing evidence {missing}")
        rows.append({**stage, "evidence_present": not missing})
    counts = Counter(stage.get("status") for stage in stages)
    implemented = counts["implemented"]
    return {
        "valid": not errors,
        "errors": errors,
        "stages": rows,
        "counts": dict(counts),
        "implementation_percent": round(implemented / len(stages) * 100, 1) if stages else 0,
        "production_gates_open": [gate["name"] for gate in config.get("production_gates", []) if gate["status"] != "closed"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = audit(load(args.config), args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.strict and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__": main()

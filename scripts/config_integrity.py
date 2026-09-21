#!/usr/bin/env python3
"""
Real config-tampering/drift detection -- closes the STRIDE Tampering
finding: "config/*.yaml -- anyone with filesystem write access can
silently change routing/safety behavior -- Unmitigated -- no config-
signing or drift-detection; this is the exact class of problem the
token-tower.yaml doc-drift finding earlier this session came from."

This is NOT trying to prevent config changes -- config SHOULD be editable.
What it closes is the "silently" part: a checksum baseline (config/
CHECKSUMS.json) is committed to git alongside the config it describes. Any
config change that doesn't also update the baseline in the same commit is
now a visible, CI-failing drift -- forcing every config change through the
same review path as a code change, rather than being invisible until
someone happens to notice the *documentation* disagrees with the *running
config* (exactly what happened with token-tower.yaml's exact_cache/
semantic_cache flags earlier this session).

Usage:
  python3 config_integrity.py check    # fails (exit 1) if drifted
  python3 config_integrity.py update   # regenerate the baseline after a
                                        # deliberate, reviewed config change
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
BASELINE_PATH = CONFIG_DIR / "CHECKSUMS.json"


def compute_checksums(config_dir: Path = CONFIG_DIR) -> dict[str, str]:
    checksums = {}
    for path in sorted(config_dir.glob("*.yaml")):
        checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return checksums


def load_baseline() -> dict[str, str]:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text())


def save_baseline(checksums: dict[str, str]) -> None:
    BASELINE_PATH.write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n")


def check_drift() -> dict:
    current = compute_checksums()
    baseline = load_baseline()
    changed = sorted(f for f in current if f in baseline and current[f] != baseline[f])
    added = sorted(f for f in current if f not in baseline)
    removed = sorted(f for f in baseline if f not in current)
    return {
        "drifted": bool(changed or added or removed),
        "changed": changed, "added": added, "removed": removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("update")
    args = parser.parse_args()

    if args.command == "update":
        save_baseline(compute_checksums())
        print(f"Baseline updated: {BASELINE_PATH}")
        return 0

    result = check_drift()
    print(json.dumps(result, indent=2))
    if result["drifted"]:
        print(
            "\nConfig drift detected -- a config/*.yaml file changed without "
            "its checksum baseline being updated in the same commit. If this "
            "change is intentional, run `python3 config_integrity.py update` "
            "and commit the updated CHECKSUMS.json alongside it.",
            file=sys.stderr,
        )
        return 1
    print("\nOK: config matches the committed baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Real task-assignment and completion-tracking for Claude -> Ollama
delegation, per this repo's own CLAUDE.md: "identify a bounded, low-risk
sub-task for local Ollama when one exists ... take responsibility for the
final answer."

execution_gateway.py already logs every real call (cache hits, inference,
blocks, errors) as "category": "model" events -- that's call-level
telemetry, correct for what it is. What's been missing is a *task*-level
record: what did Claude actually ask Ollama to do, in plain terms, and did
it finish -- something answerable from a terminal without cross-
referencing cache/GPU/routing internals.

Built as a thin wrapper around execution_gateway.execute(), not a change
to it -- execute() already has several internal branches (rate limit,
injection guard, cache tamper, PII skip, real inference, errors) and is
being actively edited elsewhere in this repo; adding a new top-level
"task" event here avoids threading another parameter through all of that.

Usage:
  python3 delegate.py run "fix the flaky test" "Explain why a pytest test \
    might pass locally but fail in CI" --kind prose
  python3 delegate.py report                    # last 20 delegated tasks
  python3 delegate.py report --limit 5 --failed-only
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import execution_gateway  # noqa: E402
from agent_monitor import EventStore  # noqa: E402

EVENTS_PATH = Path.home() / ".local/state/ollama-control-tower/monitor/events.jsonl"


def delegate(task: str, query: str, kind: str = "prose", context: str = "",
             priority: int = 0, caller_token: str | None = None) -> dict[str, Any]:
    """Assigns `task` to Ollama via the real execution gateway, records a
    real completion event, and returns the gateway's real result unchanged
    -- this wrapper adds tracking, it never alters what actually ran."""
    store = EventStore(EVENTS_PATH)
    t0 = time.monotonic()
    result = execution_gateway.execute(query, kind=kind, context=context,
                                        priority=priority, caller_token=caller_token)
    duration_ms = round((time.monotonic() - t0) * 1000, 1)

    decision = result.get("decision")
    status = "completed" if decision == "inference" else "failed" if decision == "error" else "blocked"
    store.append({
        "category": "task", "status": status, "agent_id": "claude-delegate",
        "name": task[:120], "latency_ms": duration_ms, "task_id": task[:120],
        "model": result.get("model", ""), "cache_hit": result.get("cache_hit", False),
        "decision": decision, "reason": result.get("reason", ""),
    })
    return result


def report(limit: int = 20, failed_only: bool = False) -> list[dict]:
    """Reads the real event log for delegated-task events -- terminal-
    friendly summary of what's actually been assigned and completed."""
    if not EVENTS_PATH.exists():
        return []
    tasks = []
    for line in EVENTS_PATH.read_text().splitlines()[::-1]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("category") != "task" or event.get("agent_id") != "claude-delegate":
            continue
        if failed_only and event.get("status") not in ("failed", "blocked"):
            continue
        tasks.append(event)
        if len(tasks) >= limit:
            break
    return tasks


def _print_report(tasks: list[dict]) -> None:
    if not tasks:
        print("No delegated tasks logged yet.")
        return
    for t in tasks:
        when = datetime.fromtimestamp(t["timestamp"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        mark = {"completed": "DONE", "failed": "FAILED", "blocked": "BLOCKED"}.get(t["status"], t["status"].upper())
        cache_note = " (cache hit)" if t.get("cache_hit") else ""
        print(f"[{mark:7s}] {when} | {t.get('model', '?'):20s} | {t['name']}{cache_note}")
        if t["status"] != "completed" and t.get("reason"):
            print(f"          reason: {t['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("task", help="short description of what this task is (for the report)")
    run.add_argument("query", help="the actual prompt sent to Ollama")
    run.add_argument("--kind", default="prose")
    run.add_argument("--context", default="")
    run.add_argument("--priority", type=int, default=0)
    run.add_argument("--token", default=None)

    rep = sub.add_parser("report")
    rep.add_argument("--limit", type=int, default=20)
    rep.add_argument("--failed-only", action="store_true")

    args = parser.parse_args()
    if args.command == "run":
        result = delegate(args.task, args.query, args.kind, args.context, args.priority, args.token)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("decision") == "inference" else 1

    tasks = report(args.limit, args.failed_only)
    _print_report(tasks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

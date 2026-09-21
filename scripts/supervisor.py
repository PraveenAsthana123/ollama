#!/usr/bin/env python3
"""Deterministic supervisor plan scheduler and shared blackboard."""

import argparse
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config/supervisor-tower.yaml"
FINAL_TASK = {"completed", "failed", "blocked"}


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def has_cycle(tasks: list[dict[str, Any]]) -> bool:
    graph = {task["id"]: task.get("depends_on", []) for task in tasks}
    visiting, visited = set(), set()
    def visit(node: str) -> bool:
        if node in visiting: return True
        if node in visited: return False
        visiting.add(node)
        if any(visit(dep) for dep in graph.get(node, [])): return True
        visiting.remove(node); visited.add(node)
        return False
    return any(visit(node) for node in graph)


def validate_plan(config: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, int | bool]:
    ids = [task.get("id") for task in tasks]
    if not tasks or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("tasks require unique non-empty ids")
    known = set(ids)
    routing = config.get("routing", {})
    for task in tasks:
        if task.get("agent") not in routing:
            raise ValueError(f"{task['id']}: unroutable agent {task.get('agent')}")
        unknown = set(task.get("depends_on", [])) - known
        if unknown:
            raise ValueError(f"{task['id']}: unknown dependencies {sorted(unknown)}")
        if int(task.get("depth", 1)) > config["limits"]["max_depth"]:
            raise ValueError(f"{task['id']}: delegation depth exceeded")
        approval = task.get("approval")
        allowed_approvals = config["workflow"].get("human_approval_for", [])
        if approval and approval not in allowed_approvals:
            raise ValueError(f"{task['id']}: unknown approval category {approval}")
    if has_cycle(tasks):
        raise ValueError("dependency cycle detected")
    return {"valid": True, "tasks": len(tasks)}


class PlanStore:
    def __init__(self, root: Path):
        self.root = root.expanduser(); self.root.mkdir(parents=True, exist_ok=True)
    def path(self, plan_id: str) -> Path:
        if not plan_id or not all(c.isalnum() or c in "-_" for c in plan_id): raise ValueError("invalid plan_id")
        return self.root / f"{plan_id}.json"
    def save(self, plan: dict[str, Any]) -> None:
        plan["updated_at"] = time.time()
        descriptor, temporary = tempfile.mkstemp(dir=self.root, prefix=".plan-", text=True)
        try:
            with os.fdopen(descriptor, "w") as output: json.dump(plan, output, indent=2, sort_keys=True); output.write("\n")
            os.chmod(temporary, 0o600); os.replace(temporary, self.path(plan["plan_id"]))
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
    def load(self, plan_id: str) -> dict[str, Any]: return json.loads(self.path(plan_id).read_text())


def create_plan(config: dict[str, Any], goal: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    validate_plan(config, tasks)
    normalized = [{**task, "depends_on": task.get("depends_on", []), "status": "pending", "retries": 0} for task in tasks]
    now = time.time()
    return {"plan_id": f"plan-{uuid.uuid4().hex[:12]}", "goal": goal, "status": "running",
            "tasks": normalized, "blackboard": {}, "steps": 0, "handoffs": 0,
            "tokens": 0, "cost_usd": 0.0, "no_progress": 0, "review": "pending",
            "approvals": {}, "created_at": now, "updated_at": now}


def ready_tasks(config: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    if time.time() - plan["created_at"] >= config["limits"]["timeout_seconds"]:
        plan["status"] = "timed_out"
        return []
    completed = {task["id"] for task in plan["tasks"] if task["status"] == "completed"}
    dependency_ready = [task for task in plan["tasks"] if task["status"] == "pending" and set(task["depends_on"]) <= completed]
    ready = [task for task in dependency_ready if not task.get("approval") or plan["approvals"].get(task["approval"]) == "approved"]
    if not ready and any(task["status"] == "pending" for task in plan["tasks"]):
        plan["status"] = "awaiting_approval" if dependency_ready else "deadlocked"
    elif ready and plan["status"] == "awaiting_approval":
        plan["status"] = "running"
    selected = ready[:config["limits"]["max_parallel"]]
    for task in selected:
        task["status"] = "running"; plan["handoffs"] += 1
        task["route"] = config["routing"][task["agent"]]
    return selected


def report(config: dict[str, Any], plan: dict[str, Any], task_id: str, result: dict[str, Any]) -> dict[str, Any]:
    task = next((item for item in plan["tasks"] if item["id"] == task_id), None)
    if not task or task["status"] != "running": raise ValueError("task is not running")
    plan["steps"] += 1; plan["tokens"] += max(0, int(result.get("tokens", 0)))
    plan["cost_usd"] += max(0.0, float(result.get("cost_usd", 0)))
    success = bool(result.get("success"))
    if success:
        task["status"] = "completed"; plan["blackboard"][task_id] = result.get("output", {})
        plan["no_progress"] = 0
    elif task["retries"] < config["limits"]["max_retries_per_task"]:
        task["retries"] += 1; task["status"] = "pending"; plan["no_progress"] += 1
    else:
        task["status"] = "failed"; plan["status"] = "failed"
    limits = config["limits"]
    if plan["steps"] >= limits["max_steps"] or plan["tokens"] >= limits["max_tokens"] or plan["cost_usd"] >= limits["max_cost_usd"] or plan["handoffs"] >= limits["max_handoffs"]:
        plan["status"] = "blocked"
    if plan["status"] == "running" and plan["no_progress"] >= limits["no_progress_steps"]:
        plan["status"] = "no_progress"
    if plan["status"] == "running" and all(task["status"] == "completed" for task in plan["tasks"]):
        plan["status"] = "review"
    return {"plan_status": plan["status"], "task_status": task["status"]}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=Path.home()/".local/state/ollama-control-tower/supervisor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    create = sub.add_parser("create"); create.add_argument("goal"); create.add_argument("tasks_json")
    for command in ("next", "status"):
        item = sub.add_parser(command); item.add_argument("plan_id")
    done = sub.add_parser("report"); done.add_argument("plan_id"); done.add_argument("task_id"); done.add_argument("result_json")
    review = sub.add_parser("review"); review.add_argument("plan_id"); review.add_argument("decision", choices=("accept", "reject"))
    approve = sub.add_parser("approve"); approve.add_argument("plan_id"); approve.add_argument("category")
    args = parser.parse_args(); config = load_config(args.config); store = PlanStore(args.state_dir)
    if args.command == "validate":
        result = {"valid": True, "routes": len(config["routing"]), "supervisors": len(config["hierarchy"])}
    elif args.command == "create":
        plan = create_plan(config, args.goal, json.loads(args.tasks_json)); store.save(plan); result = plan
    else:
        plan = store.load(args.plan_id)
        if args.command == "next": result = ready_tasks(config, plan); store.save(plan)
        elif args.command == "report": result = report(config, plan, args.task_id, json.loads(args.result_json)); store.save(plan)
        elif args.command == "review":
            if plan["status"] != "review": raise SystemExit("plan is not ready for review")
            plan["review"] = args.decision; plan["status"] = "completed" if args.decision == "accept" else "rework"; store.save(plan); result = plan
        elif args.command == "approve":
            if args.category not in config["workflow"].get("human_approval_for", []):
                raise SystemExit(f"unknown approval category: {args.category}")
            plan["approvals"][args.category] = "approved"
            if plan["status"] == "awaiting_approval": plan["status"] = "running"
            store.save(plan); result = plan
        else: result = plan
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__": main()

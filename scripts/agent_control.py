#!/usr/bin/env python3
"""File-backed agent control-plane state machine.

This module records control intent. Runtime adapters must observe state before
each model/tool step and perform the actual pause, cancellation, or process kill.
"""

import argparse
import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


TERMINAL = {"STOPPED", "KILLED", "COMPLETED", "BLOCKED", "HALTED"}
RUNNABLE = {"RUNNING", "STEPPING"}


@dataclass
class AgentState:
    agent_id: str
    status: str = "PAUSED"
    task: str = ""
    model: str = "fast"
    trust: str = "standard"
    tokens_used: int = 0
    token_limit: int = 30000
    cost_usd: float = 0.0
    cost_limit_usd: float = 1.0
    steps: int = 0
    step_limit: int = 50
    retries: int = 0
    reassignments: int = 0
    worker: str = ""
    blocked_tools: list[str] = field(default_factory=list)
    blocked_mcp: list[str] = field(default_factory=list)
    instruction: str = ""
    pending_action: dict[str, Any] | None = None
    recent_fingerprints: list[str] = field(default_factory=list)
    last_progress_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class StateStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, agent_id: str) -> Path:
        safe = "".join(c for c in agent_id if c.isalnum() or c in "-_")
        if not safe or safe != agent_id:
            raise ValueError("agent_id may contain only letters, numbers, '-' and '_'")
        return self.root / f"{safe}.json"

    def load(self, agent_id: str) -> AgentState:
        path = self.path(agent_id)
        if not path.exists():
            raise KeyError(f"unknown agent: {agent_id}")
        return AgentState(**json.loads(path.read_text()))

    def save(self, state: AgentState) -> None:
        state.updated_at = time.time()
        target = self.path(state.agent_id)
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".agent-", text=True)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(asdict(state), output, indent=2, sort_keys=True)
                output.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def budget_decision(state: AgentState) -> dict[str, Any]:
    token_ratio = state.tokens_used / max(state.token_limit, 1)
    cost_ratio = state.cost_usd / max(state.cost_limit_usd, 0.000001)
    if token_ratio >= 1 or cost_ratio >= 1 or state.steps >= state.step_limit:
        return {"action": "block", "reason": "budget_exhausted"}
    if token_ratio >= 0.9:
        return {"action": "degrade", "reason": "token_budget_90_percent", "model": "fast"}
    if token_ratio >= 0.8:
        return {"action": "warn", "reason": "token_budget_80_percent"}
    return {"action": "allow", "reason": "within_budget"}


def tool_decision(state: AgentState, tool: str, mcp_server: str = "") -> dict[str, str]:
    if tool in state.blocked_tools or (mcp_server and mcp_server in state.blocked_mcp):
        return {"action": "block", "reason": "agent_policy"}
    if tool in {"credential.export", "sandbox.disable"}:
        return {"action": "block", "reason": "global_policy"}
    risky = {"git.push", "deploy.production", "email.send", "database.delete",
             "filesystem.delete", "package.system_install", "memory.persist",
             # browser.external_form_fill: added 2026-09-21 -- job-portal's
             # real fill_application task interacts with a real third-party
             # company's website. It was found classified "allow" by
             # omission (this set predates that real use case), which meant
             # the one genuinely real risky action in the whole repo was
             # silently NOT flagged by the policy engine meant to catch it.
             "browser.external_form_fill"}
    if tool in risky or state.trust == "restricted":
        return {"action": "review", "reason": "approval_required"}
    return {"action": "allow", "reason": "policy_allows"}


def apply_event(state: AgentState, event: dict[str, Any]) -> dict[str, Any]:
    if state.status not in RUNNABLE:
        return {"action": "block", "reason": f"agent_{state.status.lower()}"}
    state.tokens_used += max(0, int(event.get("tokens", 0)))
    state.cost_usd += max(0.0, float(event.get("cost_usd", 0)))
    state.steps += 1
    if event.get("progress", True):
        state.last_progress_at = time.time()
    mark = fingerprint({"tool": event.get("tool"), "state": event.get("state")})
    state.recent_fingerprints = (state.recent_fingerprints + [mark])[-3:]
    if len(state.recent_fingerprints) == 3 and len(set(state.recent_fingerprints)) == 1:
        state.status = "HALTED"
        return {"action": "halt", "reason": "repeated_state_or_tool_call"}
    decision = budget_decision(state)
    if decision["action"] == "block":
        state.status = "BLOCKED"
    elif decision["action"] == "degrade":
        state.model = decision["model"]
    elif state.status == "STEPPING":
        state.status = "PAUSED"
    return decision


def control(state: AgentState, action: str, value: str | None) -> dict[str, Any]:
    if action == "pause" and state.status not in TERMINAL:
        state.status = "PAUSED"
    elif action == "resume" and state.status not in TERMINAL:
        state.status = "RUNNING"
    elif action == "step" and state.status not in TERMINAL:
        state.status = "STEPPING"
    elif action == "stop" and state.status not in TERMINAL:
        state.status = "STOPPED"
    elif action == "kill" and state.status not in TERMINAL:
        state.status = "KILLED"
    elif action == "redirect":
        state.instruction = value or ""
    elif action == "reassign":
        state.worker = value or ""
        state.reassignments += 1
    elif action == "model":
        state.model = value or state.model
    elif action == "block-tool" and value and value not in state.blocked_tools:
        state.blocked_tools.append(value)
    elif action == "block-mcp" and value and value not in state.blocked_mcp:
        state.blocked_mcp.append(value)
    elif action == "approve" and state.pending_action:
        state.pending_action["decision"] = "approved"
        state.status = "RUNNING"
    elif action == "reject" and state.pending_action:
        state.pending_action["decision"] = "rejected"
        state.status = "PAUSED"
    else:
        if action not in {"redirect", "reassign", "model", "block-tool", "block-mcp"}:
            raise ValueError(f"action not valid from {state.status}: {action}")
    return {"action": action, "status": state.status}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/ollama-control-tower/agents")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("agent_id")
    create.add_argument("--task", default="")
    create.add_argument("--model", default="fast")
    create.add_argument("--worker", default="")
    create.add_argument("--trust", choices=("restricted", "standard", "trusted"), default="standard")
    status = sub.add_parser("status"); status.add_argument("agent_id")
    event = sub.add_parser("event"); event.add_argument("agent_id"); event.add_argument("event_json")
    tool = sub.add_parser("check-tool"); tool.add_argument("agent_id"); tool.add_argument("tool"); tool.add_argument("--mcp", default="")
    for name in ("pause", "resume", "step", "stop", "kill", "approve", "reject"):
        item = sub.add_parser(name); item.add_argument("agent_id")
    for name in ("redirect", "reassign", "model", "block-tool", "block-mcp"):
        item = sub.add_parser(name); item.add_argument("agent_id"); item.add_argument("value")
    args = parser.parse_args()
    store = StateStore(args.state_dir)
    if args.command == "create":
        state = AgentState(args.agent_id, task=args.task, model=args.model,
                           worker=args.worker, trust=args.trust)
        store.save(state); result = asdict(state)
    else:
        state = store.load(args.agent_id)
        if args.command == "status":
            result = {**asdict(state), "budget": budget_decision(state)}
        elif args.command == "event":
            result = apply_event(state, json.loads(args.event_json)); store.save(state)
        elif args.command == "check-tool":
            result = tool_decision(state, args.tool, args.mcp)
        else:
            result = control(state, args.command, getattr(args, "value", None)); store.save(state)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

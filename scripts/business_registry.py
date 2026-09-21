#!/usr/bin/env python3
"""Validate and query the Business Agent Registry."""

import argparse
import json
from pathlib import Path

import yaml


DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "config/business-agent-registry.yaml"


def load_registry(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("registry root must be a mapping")
    return data


def validate_registry(registry: dict) -> dict:
    errors = []
    required = {"domain", "department", "work", "skills", "tool_profile", "agents"}
    profiles = registry.get("tool_profiles", {})
    domains = registry.get("domains", [])
    supervisors = registry.get("supervisors", {})
    technical = set(registry.get("technical_agents", []))
    roles = {}
    covered = {domain for values in supervisors.values() for domain in values}

    for index, item in enumerate(domains):
        missing = required - set(item)
        if missing:
            errors.append(f"domain[{index}] missing: {', '.join(sorted(missing))}")
            continue
        if item["tool_profile"] not in profiles:
            errors.append(f"{item['domain']}: unknown tool profile {item['tool_profile']}")
        if item["domain"] not in covered:
            errors.append(f"{item['domain']}: no supervisor")
        for role in item["agents"]:
            roles.setdefault(role, []).append(item["domain"])

    for workflow, spec in registry.get("workflows", {}).items():
        for role in spec.get("chain", []):
            if role not in roles and role not in technical:
                errors.append(f"workflow {workflow}: unknown role {role}")

    if errors:
        raise ValueError("\n".join(errors))
    return {
        "valid": True,
        "domains": len(domains),
        "role_assignments": sum(len(item["agents"]) for item in domains),
        "unique_roles": len(roles),
        "supervisors": len(supervisors),
        "workflows": len(registry.get("workflows", {})),
    }


def resolved_agents(registry: dict) -> list[dict]:
    profiles = registry["tool_profiles"]
    supervisor_for = {
        domain: supervisor
        for supervisor, domains in registry["supervisors"].items()
        for domain in domains
    }
    result = []
    for item in registry["domains"]:
        for role in item["agents"]:
            result.append({
                "domain": item["domain"],
                "department": item["department"],
                "role": role,
                "skills": item["skills"],
                "tools": profiles[item["tool_profile"]],
                "supervisor": supervisor_for[item["domain"]],
                "technical_agent": role in registry.get("technical_agents", []),
            })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    listing = sub.add_parser("list")
    listing.add_argument("--domain")
    show = sub.add_parser("show")
    show.add_argument("role")
    workflow = sub.add_parser("workflow")
    workflow.add_argument("name")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    summary = validate_registry(registry)
    if args.command == "validate":
        result = summary
    elif args.command == "list":
        result = resolved_agents(registry)
        if args.domain:
            result = [agent for agent in result if agent["domain"].casefold() == args.domain.casefold()]
    elif args.command == "show":
        result = [agent for agent in resolved_agents(registry) if agent["role"].casefold() == args.role.casefold()]
        if not result:
            raise SystemExit(f"unknown role: {args.role}")
    else:
        try:
            result = registry["workflows"][args.name]
        except KeyError:
            raise SystemExit(f"unknown workflow: {args.name}") from None
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

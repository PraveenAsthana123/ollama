#!/usr/bin/env python3
"""Deterministic token budgeting, context pruning, routing, and cache keys.

This utility performs no model call. It prepares a bounded request for LiteLLM
or Ollama and emits auditable JSON suitable for a gateway or agent supervisor.
"""

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.:/-]*|\d+")
ERROR = re.compile(r"error|exception|failed|fatal|traceback|panic|denied|timeout", re.I)
CODE = re.compile(r"\b(class|def|function|import|from|return|async|await|SELECT|INSERT|UPDATE|DELETE)\b|[{}();]", re.I)


@dataclass
class PreparedRequest:
    cache_key: str
    route: str
    source_kind: str
    estimated_input_tokens_before: int
    estimated_input_tokens_after: int
    input_budget_tokens: int
    output_limit_tokens: int
    compression_ratio: float
    duplicate_context_ratio: float
    context: str


def estimate_tokens(text: str) -> int:
    # A transparent conservative approximation for routing; the model tokenizer
    # remains authoritative at inference time.
    return max(1, math.ceil(len(text) / 3.5)) if text else 0


def terms(text: str) -> set[str]:
    return {term.lower() for term in WORD.findall(text) if len(term) > 2}


def score_line(line: str, query_terms: set[str], kind: str) -> float:
    line_terms = terms(line)
    overlap = len(query_terms & line_terms)
    score = overlap * 8 + min(len(line_terms), 20) * 0.05
    if kind == "logs" and ERROR.search(line):
        score += 6
    if kind == "source" and CODE.search(line):
        score += 2
    if kind == "history" and line.lstrip().startswith(("USER:", "ASSISTANT:")):
        score += 1
    return score


def prune(query: str, context: str, kind: str, budget: int) -> str:
    if estimate_tokens(context) <= budget:
        return context
    lines = context.splitlines()
    query_terms = terms(query)
    ranked = sorted(
        enumerate(lines), key=lambda item: (-score_line(item[1], query_terms, kind), item[0])
    )
    selected: set[int] = set()
    used = 0
    for index, line in ranked:
        # Retain a small neighborhood because isolated source/log lines often
        # lose the evidence that explains them.
        for candidate in range(max(0, index - 1), min(len(lines), index + 2)):
            cost = estimate_tokens(lines[candidate] + "\n")
            if candidate not in selected and used + cost <= budget:
                selected.add(candidate)
                used += cost
        if used >= budget * 0.95:
            break
    return "\n".join(lines[index] for index in sorted(selected))


def duplicate_ratio(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return round(1 - len(set(lines)) / len(lines), 4) if lines else 0.0


def compress_observation(observation: str, budget: int) -> str:
    """Loss-aware fallback compressor for terminal/tool observations.

    Keeps unique lines, errors, action-bearing output, and the final state. A
    learned CoACT-compatible adapter can replace this at the gateway boundary.
    """
    lines = observation.splitlines()
    unique, seen = [], set()
    for index, line in enumerate(lines):
        normalized = line.strip()
        if normalized and normalized in seen and not ERROR.search(line):
            continue
        if normalized:
            seen.add(normalized)
        priority = 10 if ERROR.search(line) else 5 if CODE.search(line) else 2 if index >= len(lines) - 10 else 1
        unique.append((index, line, priority))
    selected, used = set(), 0
    for index, line, _ in sorted(unique, key=lambda item: (-item[2], -item[0])):
        cost = estimate_tokens(line + "\n")
        if used + cost <= budget:
            selected.add(index); used += cost
    return "\n".join(lines[index] for index in sorted(selected))


def choose_route(query: str, context_tokens: int, kind: str) -> str:
    text = query.lower()
    hard = ("architecture", "security", "migrate", "root cause", "proof", "research")
    code = ("code", "bug", "test", "docker", "sql", "python", "javascript", "typescript")
    if context_tokens > 6500 or any(word in text for word in hard):
        return "strong"
    if kind == "source" or any(word in text for word in code):
        return "code"
    return "fast"


def output_limit(query: str, route: str) -> int:
    text = query.lower()
    if any(word in text for word in ("one word", "brief", "short", "classify", "yes or no")):
        return 128
    return {"fast": 512, "code": 1024, "strong": 1024}[route]


def prepare(query: str, context: str, kind: str, input_budget: int) -> PreparedRequest:
    before = estimate_tokens(context)
    bounded = prune(query, context, kind, input_budget)
    after = estimate_tokens(bounded)
    route = choose_route(query, after, kind)
    normalized = json.dumps({"query": query, "context": bounded, "kind": kind,
                             "route": route}, sort_keys=True, separators=(",", ":"))
    return PreparedRequest(
        cache_key=hashlib.sha256(normalized.encode()).hexdigest(),
        route=route,
        source_kind=kind,
        estimated_input_tokens_before=before,
        estimated_input_tokens_after=after,
        input_budget_tokens=input_budget,
        output_limit_tokens=output_limit(query, route),
        compression_ratio=round(after / before, 4) if before else 1.0,
        duplicate_context_ratio=duplicate_ratio(context),
        context=bounded,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--kind", choices=("history", "source", "logs", "prose"), default="prose")
    parser.add_argument("--input-budget", type=int, default=3500)
    parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args()
    context = args.path.read_text(errors="replace") if args.path else sys.stdin.read()
    print(json.dumps(asdict(prepare(args.query, context, args.kind, args.input_budget)), indent=2))


if __name__ == "__main__":
    main()

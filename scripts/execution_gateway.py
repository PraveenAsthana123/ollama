#!/usr/bin/env python3
"""
Real execution gateway -- the gap an independent external audit (2026-09-21,
cross-checked against this repo's actual state before acting on it) called
the single biggest missing component: inference_router.py only ever
produced a routing *decision*, nothing in this repo actually executed it
against a real model.

This module closes that gap for the one path that's genuinely enabled today
(direct_ollama -- pair/free_cloud/paid_cloud are all still disabled in
config/inference-control-tower.yaml, so this does not claim to execute
paths that don't exist yet):

  request
    -> real Redis exact-cache check (config/token-tower.yaml: exact_cache)
    -> inference_router.route() for the real routing decision
    -> real HTTP call to Ollama for the chosen model (direct_ollama only)
    -> cache the result
    -> real event logged to agent_monitor's event store

Deliberately NOT implemented here (would be fabricating capability that
doesn't exist): semantic cache (needs a real Qdrant deployment -- config
still says qdrant/disabled, no Qdrant instance on this machine), pair/
free_cloud/paid_cloud execution (all disabled in config, no credentials
wired), automatic Claude escalation (no such mechanism exists -- see
docs/OLLAMA_FIRST_STRATEGY.md's own explicit statement on this).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inference_router  # noqa: E402
import gpu_scheduler  # noqa: E402
from agent_monitor import EventStore  # noqa: E402

try:
    import redis
except ImportError:
    redis = None

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_CONFIG = REPO_ROOT / "config/inference-control-tower.yaml"
TOKEN_TOWER_CONFIG = REPO_ROOT / "config/token-tower.yaml"
EVENTS_PATH = Path.home() / ".local/state/ollama-control-tower/monitor/events.jsonl"

_redis_client = None
if redis is not None:
    try:
        _redis_client = redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=1, socket_timeout=2)
        _redis_client.ping()
    except Exception:
        _redis_client = None


def _cache_key(query: str, kind: str, context: str) -> str:
    digest = hashlib.sha256(f"{kind}:{context}:{query}".encode("utf-8")).hexdigest()
    return f"execution_gateway:exact:{digest}"


def _ollama_tags(endpoint: str) -> list[str]:
    """Real installed-model list -- used to populate route()'s availability
    dict honestly, never assumed."""
    req = urllib.request.Request(f"{endpoint}/api/tags")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_generate(endpoint: str, model: str, query: str, keep_alive: str, timeout: int = 90) -> dict:
    payload = {"model": model, "prompt": query, "stream": False, "keep_alive": keep_alive}
    req = urllib.request.Request(
        f"{endpoint}/api/generate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def execute(query: str, kind: str = "prose", context: str = "", priority: int = 0) -> dict[str, Any]:
    inference_config = yaml.safe_load(INFERENCE_CONFIG.read_text())
    token_config = yaml.safe_load(TOKEN_TOWER_CONFIG.read_text())
    exact_cache_cfg = token_config["pipeline"]["exact_cache"]
    keep_alive = token_config["defaults"]["keep_alive"]
    store = EventStore(EVENTS_PATH)

    t0 = time.monotonic()
    cache_key = _cache_key(query, kind, context)

    if exact_cache_cfg["enabled"] and _redis_client:
        try:
            cached = _redis_client.get(cache_key)
        except Exception:
            cached = None
        if cached:
            result = json.loads(cached)
            result["cache_hit"] = True
            result["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)
            store.append({
                "category": "model", "status": "completed", "agent_id": "execution_gateway",
                "name": result.get("model", "cache"), "latency_ms": result["latency_ms"],
                "cached_tokens": 1, "decision": "cache",
            })
            return result

    direct = inference_config["local"]["direct_ollama"]
    endpoint = direct["endpoint"]
    installed = _ollama_tags(endpoint) if direct["enabled"] else []
    availability = {
        "direct_ollama": {"healthy": bool(installed), "models": installed},
        "pair": {"healthy": False, "models": []},
        "free_cloud": {"healthy": False, "quota_available": False},
        "paid_cloud": {"healthy": False},
    }

    request = {"query": query, "kind": kind, "context": context}
    plan = inference_router.route(inference_config, request, availability)

    if plan["decision"] != "inference":
        result = {
            "cache_hit": False, "decision": plan["decision"], "reason": plan.get("reason"),
            "tier": plan.get("tier"), "stages": plan.get("stages", []),
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
        store.append({
            "category": "model", "status": "blocked", "agent_id": "execution_gateway",
            "name": plan.get("tier", "unknown"), "latency_ms": result["latency_ms"],
            "reason": result["reason"] or "unrouted",
        })
        return result

    if plan["provider"] != "direct_ollama":
        # Routing chose a provider this gateway doesn't execute yet -- report
        # that honestly rather than silently falling back to direct_ollama.
        result = {
            "cache_hit": False, "decision": "not_executable",
            "reason": f"provider {plan['provider']!r} is routed but has no execution adapter in this gateway yet",
            "plan": plan, "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
        store.append({
            "category": "model", "status": "blocked", "agent_id": "execution_gateway",
            "name": plan["model"], "latency_ms": result["latency_ms"], "reason": "no_execution_adapter",
        })
        return result

    try:
        gpu_client = gpu_scheduler._client()
    except Exception:
        gpu_client = None  # scheduler is additive: Redis being down must not block inference

    def _fail(reason: str) -> dict:
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        store.append({
            "category": "model", "status": "failed", "agent_id": "execution_gateway",
            "name": plan["model"], "latency_ms": latency_ms, "reason": reason,
        })
        return {"cache_hit": False, "decision": "error", "reason": reason, "plan": plan, "latency_ms": latency_ms}

    if gpu_client is not None:
        try:
            lease_cm = gpu_scheduler.acquire(priority, timeout=120, client=gpu_client)
            lease = lease_cm.__enter__()
        except TimeoutError as exc:
            return _fail(f"gpu_lease_timeout: {exc}")
    else:
        lease_cm = None
        lease = {"wait_ms": 0.0, "priority_name": "unscheduled"}

    try:
        response = _ollama_generate(endpoint, plan["model"], query, keep_alive)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        if lease_cm is not None:
            lease_cm.__exit__(type(exc), exc, exc.__traceback__)
        return _fail(f"{type(exc).__name__}: {exc}")
    else:
        if lease_cm is not None:
            lease_cm.__exit__(None, None, None)

    latency_ms = round((time.monotonic() - t0) * 1000, 1)
    result = {
        "cache_hit": False, "decision": "inference", "provider": plan["provider"],
        "model": plan["model"], "tier": plan["tier"], "stages": plan["stages"],
        "response": response.get("response", ""), "latency_ms": latency_ms,
        "gpu_wait_ms": lease["wait_ms"], "gpu_priority": lease["priority_name"],
    }

    if exact_cache_cfg["enabled"] and _redis_client:
        try:
            cacheable = dict(result)
            cacheable.pop("cache_hit", None)
            cacheable.pop("latency_ms", None)
            _redis_client.setex(cache_key, exact_cache_cfg["ttl_seconds"], json.dumps(cacheable))
        except Exception:
            pass

    store.append({
        "category": "model", "status": "completed", "agent_id": "execution_gateway",
        "name": plan["model"], "latency_ms": latency_ms, "provider": plan["provider"],
        "tier": plan["tier"], "output_tokens": len(result["response"].split()),
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--kind", default="prose")
    parser.add_argument("--context", default="")
    parser.add_argument("--priority", type=int, default=0, choices=list(gpu_scheduler.PRIORITY_NAMES),
                         help="0=interactive 1=coding 2=embedding 3=image 4=video 5=batch")
    args = parser.parse_args()
    print(json.dumps(execute(args.query, args.kind, args.context, args.priority), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

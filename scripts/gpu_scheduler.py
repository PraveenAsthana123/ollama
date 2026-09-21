#!/usr/bin/env python3
"""
Real GPU lease manager -- closes the "GPU scheduler: MISSING" gap the
external audit flagged (2026-09-21). This machine's Ollama is configured
with OLLAMA_NUM_PARALLEL=1 (real, verified via `systemctl show ollama`),
meaning exactly one GPU inference request can run at a time regardless of
how many callers ask concurrently. Without a scheduler, concurrent callers
just block inside Ollama's own queue with no priority, no visibility, and
no fairness. This gives execution_gateway.py (and, later, any image/video
job) a real priority queue and a real single-slot lease in front of that
bottleneck.

Priority classes (lower number = served first), matching the work classes
in the external audit's own Section 27:
  0 = interactive text  (execution_gateway direct calls)
  1 = coding
  2 = embedding/reranking
  3 = image            (no real caller yet -- ComfyUI isn't integrated)
  4 = video             (no real caller yet)
  5 = batch/audit

Implemented with Redis (already relied on elsewhere in this project for
caching -- proven reliable) rather than in-process locking, because real
callers are separate CLI processes (each `control-tower run` invocation is
its own process), so an in-process threading.Lock would not coordinate
across them.

Deliberately NOT implemented: VRAM-size-aware admission (would require
per-model VRAM footprints this repo doesn't track yet), preemption of a
running job (Ollama itself offers no cancel-in-flight API this repo can
call). Both noted here rather than silently assumed.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from contextlib import contextmanager
from typing import Iterator

try:
    import redis
except ImportError:
    redis = None

QUEUE_KEY = "gpu_scheduler:queue"        # sorted set: member=job_id, score=priority*1e13+arrival_ts
LOCK_KEY = "gpu_scheduler:lease"         # single-slot lock: holder job_id, with TTL
LOCK_TTL_SECONDS = 120                   # generous ceiling above any observed cold-load time (measured max ~50s)
POLL_INTERVAL_SECONDS = 0.05

PRIORITY_NAMES = {0: "interactive", 1: "coding", 2: "embedding", 3: "image", 4: "video", 5: "batch"}


def _client():
    if redis is None:
        raise RuntimeError("redis package not installed -- GPU scheduler requires it (see requirements)")
    client = redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=1, socket_timeout=2)
    client.ping()
    return client


def queue_depth(client) -> int:
    return client.zcard(QUEUE_KEY)


def queue_snapshot(client) -> list[dict]:
    entries = client.zrange(QUEUE_KEY, 0, -1, withscores=True)
    out = []
    for member, score in entries:
        job_id = member.decode() if isinstance(member, bytes) else member
        priority = int(score // 10**13)
        arrival_ts = score - priority * 10**13
        out.append({"job_id": job_id, "priority": priority, "priority_name": PRIORITY_NAMES.get(priority, "?"),
                     "arrival_ts": arrival_ts})
    return out


@contextmanager
def acquire(priority: int, job_id: str | None = None, timeout: float = 90.0,
            client=None) -> Iterator[dict]:
    """Blocks (polling, priority-ordered) until this job holds the single
    GPU lease, yields real wait-time metrics, then releases on exit --
    including on exception, so a failed inference never leaks the lease."""
    own_client = client is None
    if own_client:
        client = _client()
    job_id = job_id or str(uuid.uuid4())
    arrival = time.monotonic()
    arrival_ts = time.time()
    score = priority * 10**13 + arrival_ts
    client.zadd(QUEUE_KEY, {job_id: score})

    acquired = False
    try:
        deadline = arrival + timeout
        while time.monotonic() < deadline:
            head = client.zrange(QUEUE_KEY, 0, 0)
            at_head = bool(head) and (head[0].decode() if isinstance(head[0], bytes) else head[0]) == job_id
            if at_head and client.set(LOCK_KEY, job_id, nx=True, ex=LOCK_TTL_SECONDS):
                acquired = True
                break
            time.sleep(POLL_INTERVAL_SECONDS)

        if not acquired:
            raise TimeoutError(f"gpu lease not acquired within {timeout}s (queue_depth={queue_depth(client)})")

        wait_ms = round((time.monotonic() - arrival) * 1000, 1)
        yield {"job_id": job_id, "priority": priority, "priority_name": PRIORITY_NAMES.get(priority, "?"),
               "wait_ms": wait_ms}
    finally:
        client.zrem(QUEUE_KEY, job_id)
        if acquired:
            # only release a lease we actually hold -- never clear another
            # job's lock if our own TTL already expired and something else
            # legitimately acquired it in between
            held_by = client.get(LOCK_KEY)
            held_by = held_by.decode() if isinstance(held_by, bytes) else held_by
            if held_by == job_id:
                client.delete(LOCK_KEY)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    args = parser.parse_args()
    client = _client()
    if args.command == "status":
        held_by = client.get(LOCK_KEY)
        held_by = held_by.decode() if isinstance(held_by, bytes) else held_by
        print(json.dumps({
            "lease_held_by": held_by,
            "queue_depth": queue_depth(client),
            "queue": queue_snapshot(client),
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

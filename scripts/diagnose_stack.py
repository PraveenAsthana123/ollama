#!/usr/bin/env python3
"""Read-only live diagnostics for the local Ollama control stack."""

import json
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _get(url):
    if not url.startswith("http://127.0.0.1:11434/api/"):
        raise ValueError("Diagnostics only permits local Ollama API reads")
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # nosemgrep: dynamic-urllib-use-detected -- validated fixed local API prefix above
            return json.load(response)
    except Exception as exc:
        return {"error": type(exc).__name__}


def _unit(name):
    result = subprocess.run(["systemctl", "--user", "is-active", name],
                            capture_output=True, text=True, timeout=3)
    return result.stdout.strip() if result.returncode == 0 else "inactive"


def snapshot():
    version = _get("http://127.0.0.1:11434/api/version")
    tags = _get("http://127.0.0.1:11434/api/tags")
    resident = _get("http://127.0.0.1:11434/api/ps")
    try:
        with urllib.request.urlopen("http://127.0.0.1:6333/healthz", timeout=3):  # nosemgrep: dynamic-urllib-use-detected -- fixed loopback health endpoint
            qdrant_ok = True
    except Exception:
        qdrant_ok = False
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=3):
            redis_ok = True
    except OSError:
        redis_ok = False
    events_path = Path.home() / ".local/state/ollama-control-tower/monitor/events.jsonl"
    events = []
    if events_path.exists():
        for line in events_path.read_text().splitlines()[-200:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    failures = [e for e in events if e.get("status") in {"failed", "blocked"}]
    units = {name: _unit(name) for name in
             ("ollama.service", "ollama-portal.service", "ollama-prewarm.timer")}
    problems = []
    if "error" in version:
        problems.append("Ollama API unavailable")
    if not qdrant_ok:
        problems.append("Qdrant semantic cache unavailable")
    if not redis_ok:
        problems.append("Redis exact cache / GPU scheduling unavailable")
    if units["ollama-portal.service"] != "active":
        problems.append("Portal service inactive")
    if units["ollama-prewarm.timer"] != "active":
        problems.append("Prewarm timer inactive")
    if not resident.get("models"):
        problems.append("No model resident: next request may cold-start")
    if failures:
        problems.append(f"{len(failures)} recent blocked/failed events in last 200")
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "ollama_version": version.get("version"),
        "installed_models": len(tags.get("models", [])),
        "caches": {"qdrant": qdrant_ok, "redis": redis_ok},
        "resident_models": [m.get("name", "") for m in resident.get("models", [])],
        "units": units, "recent_events": len(events),
        "recent_failures": failures[-10:], "problems": problems,
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))

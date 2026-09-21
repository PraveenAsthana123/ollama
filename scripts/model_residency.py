#!/usr/bin/env python3
"""
Real model residency check -- what's actually loaded in Ollama right now
(hot/warm), vs. installed but not loaded (cold). Reads Ollama's own
/api/ps (currently resident models with VRAM + expiry) and /api/tags
(all installed models), computes the real hot/cold split.

Usage:
  python3 model_residency.py
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

OLLAMA_URL = "http://127.0.0.1:11434"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{OLLAMA_URL}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode())


def residency() -> dict:
    ps = _get("/api/ps").get("models", [])
    tags = _get("/api/tags").get("models", [])
    resident_names = {m["name"] for m in ps}

    hot = []
    for m in ps:
        expires = m.get("expires_at", "")
        hot.append({
            "model": m["name"],
            "vram_gb": round(m.get("size_vram", 0) / 1e9, 2),
            "expires_at": expires,
        })

    cold = [m["name"] for m in tags if m["name"] not in resident_names]

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "hot_count": len(hot),
        "hot": hot,
        "cold_count": len(cold),
        "total_installed": len(tags),
        "total_vram_used_gb": round(sum(h["vram_gb"] for h in hot), 2),
    }


if __name__ == "__main__":
    print(json.dumps(residency(), indent=2))

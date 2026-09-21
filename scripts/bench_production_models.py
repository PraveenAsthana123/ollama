#!/usr/bin/env python3
"""
Real production-model benchmark -- Profile A/B/C/D pattern from the
"Ollama Local AI Super Platform" action prompt (2026-09-21), scoped to the
models actually used in production (job-portal's gemma2:9b + nomic-embed-text)
rather than a full model-portfolio sweep. Measures cold AND warm for each,
since that distinction is the real story on this machine (76s cold vs.
sub-5s warm, confirmed earlier the same day).

Usage:
  python3 bench_production_models.py
"""

from __future__ import annotations

import json
import time
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"

PROFILES = {
    "A_smoke_8tok": "Say hi.",
    "B_interactive_128tok": "Explain what a QA engineer does in 2 sentences.",
    "C_normal_512tok": (
        "RESUME: 8 years QA experience, Playwright, Selenium, SQL, Postman, Azure DevOps.\n\n"
        "JOB: Seeking a QA engineer with 5+ years experience, Cypress, Python, AWS.\n\n"
        "What are the genuine gaps? Be thorough."
    ),
}


def unload(model: str) -> None:
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


def timed_generate(model: str, prompt: str) -> dict:
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
    elapsed = time.monotonic() - t0
    eval_count = result.get("eval_count", 0)
    eval_duration_s = result.get("eval_duration", 0) / 1e9
    return {
        "total_s": round(elapsed, 2),
        "tokens_generated": eval_count,
        "tokens_per_sec": round(eval_count / eval_duration_s, 1) if eval_duration_s else None,
        "load_duration_s": round(result.get("load_duration", 0) / 1e9, 2),
    }


def timed_embed(model: str, text: str) -> dict:
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=json.dumps({"model": model, "prompt": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        json.loads(resp.read().decode())
    return {"total_s": round(time.monotonic() - t0, 2)}


def main() -> None:
    results = {}

    print("=== gemma2:9b (chat) ===")
    unload("gemma2:9b")
    print("  cold run...")
    results["gemma2:9b_cold_A"] = timed_generate("gemma2:9b", PROFILES["A_smoke_8tok"])
    print(f"    {results['gemma2:9b_cold_A']}")
    for name, prompt in list(PROFILES.items())[1:]:
        print(f"  warm run ({name})...")
        results[f"gemma2:9b_warm_{name}"] = timed_generate("gemma2:9b", prompt)
        print(f"    {results[f'gemma2:9b_warm_{name}']}")

    print("\n=== nomic-embed-text (embed) ===")
    unload("nomic-embed-text")
    print("  cold run...")
    results["embed_cold"] = timed_embed("nomic-embed-text", "cold start benchmark text")
    print(f"    {results['embed_cold']}")
    print("  warm run...")
    results["embed_warm"] = timed_embed("nomic-embed-text", "warm benchmark text, different content")
    print(f"    {results['embed_warm']}")

    print("\n=== Summary ===")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

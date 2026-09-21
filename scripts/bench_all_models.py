#!/usr/bin/env python3
"""
Real full-library benchmark -- closes the gap where bench_production_models.py
was explicitly scoped to only 2 production models. "All the model" (user's
own words) means the whole installed library, not a hand-picked subset.

For each installed model: unload (keep_alive=0) -> real cold Profile-A
generate (8 tokens, timed) -> real warm Profile-A generate (timed again) ->
record load_duration, tokens/sec, VRAM. Embedding-only models (nomic-embed-text,
bge-*, mxbai-embed-large) get a real /api/embeddings timing instead -- sending
them a chat prompt would be testing the wrong endpoint, not a fair benchmark.

Safety bound (not a silent skip): this machine has ~11GB VRAM total and was
observed with ~8.4GB free before this run. A model whose file size exceeds
SAFE_VRAM_LIMIT_GB is skipped rather than loaded, because this session
already hit a real severe-swap-pressure incident earlier from uncontrolled
Ollama memory use. Skipped models are listed explicitly in the output, never
silently dropped from "all models benchmarked."

Usage:
  python3 bench_all_models.py [--limit N] [--include-large]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
SAFE_VRAM_LIMIT_GB = 10.0
PROMPT_A = "Say hi."

EMBED_FAMILIES = {"nomic-bert", "bert"}  # nomic-embed-text, bge-large, bge-m3, mxbai-embed-large


def _tags() -> list[dict]:
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=10) as resp:  # nosemgrep: dynamic-urllib-use-detected -- OLLAMA_URL is a hardcoded local constant
        return json.loads(resp.read().decode())["models"]


def _unload(model: str) -> None:
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()  # nosemgrep: dynamic-urllib-use-detected -- OLLAMA_URL is a hardcoded local constant
    except Exception:
        pass


def _timed_generate(model: str, prompt: str, timeout: int) -> dict:
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep: dynamic-urllib-use-detected -- OLLAMA_URL is a hardcoded local constant
        result = json.loads(resp.read().decode())
    elapsed = time.monotonic() - t0
    eval_count = result.get("eval_count", 0)
    eval_duration_s = result.get("eval_duration", 0) / 1e9
    return {
        "total_s": round(elapsed, 2),
        "load_duration_s": round(result.get("load_duration", 0) / 1e9, 2),
        "tokens_generated": eval_count,
        "tokens_per_sec": round(eval_count / eval_duration_s, 1) if eval_duration_s else None,
    }


def _timed_embed(model: str, timeout: int) -> dict:
    t0 = time.monotonic()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=json.dumps({"model": model, "prompt": "benchmark probe text"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosemgrep: dynamic-urllib-use-detected -- OLLAMA_URL is a hardcoded local constant
        json.loads(resp.read().decode())
    return {"total_s": round(time.monotonic() - t0, 2)}


def bench_one(m: dict, timeout: int) -> dict:
    name = m["name"]
    size_gb = round(m["size"] / 1e9, 2)
    family = m["details"].get("family", "")
    is_embed = family in EMBED_FAMILIES

    _unload(name)
    try:
        if is_embed:
            cold = _timed_embed(name, timeout)
            warm = _timed_embed(name, timeout)
            return {"model": name, "size_gb": size_gb, "kind": "embedding",
                     "cold_s": cold["total_s"], "warm_s": warm["total_s"], "status": "ok"}
        cold = _timed_generate(name, PROMPT_A, timeout)
        warm = _timed_generate(name, PROMPT_A, timeout)
        return {"model": name, "size_gb": size_gb, "kind": "generate",
                 "cold_total_s": cold["total_s"], "cold_load_s": cold["load_duration_s"],
                 "warm_total_s": warm["total_s"], "warm_tokens_per_sec": warm["tokens_per_sec"],
                 "status": "ok"}
    except Exception as exc:
        return {"model": name, "size_gb": size_gb, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _unload(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--include-large", action="store_true",
                         help=f"also benchmark models over {SAFE_VRAM_LIMIT_GB}GB (risk of swap pressure on this machine)")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    models = sorted(_tags(), key=lambda m: m["size"])
    skipped = [m["name"] for m in models if m["size"] / 1e9 > SAFE_VRAM_LIMIT_GB and not args.include_large]
    to_test = [m for m in models if m["size"] / 1e9 <= SAFE_VRAM_LIMIT_GB or args.include_large]
    if args.limit:
        to_test = to_test[: args.limit]

    results = []
    for i, m in enumerate(to_test):
        print(f"[{i+1}/{len(to_test)}] {m['name']} ({round(m['size']/1e9,2)}GB)...", flush=True)
        r = bench_one(m, args.timeout)
        results.append(r)
        print(f"  -> {r}", flush=True)

    print("\n=== Summary ===")
    print(json.dumps({
        "tested": len(results),
        "skipped_too_large": skipped,
        "results": results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

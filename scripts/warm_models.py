#!/usr/bin/env python3
"""Preload the latency-sensitive Ollama models and keep them resident."""

import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor


BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
MODELS = [m.strip() for m in os.getenv(
    "OLLAMA_WARM_MODELS", "qwen3:1.7b,qwen2.5-coder:1.5b"
).split(",") if m.strip()]
KEEP_ALIVE = os.getenv("OLLAMA_WARM_KEEP_ALIVE", "30m")


def request(path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE_URL + path, body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def main() -> None:
    def warm(model: str) -> str:
        result = request("/api/generate", {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_ctx": 4096, "num_predict": 1},
        })
        if result.get("error"):
            raise RuntimeError(f"{model}: {result['error']}")
        return model

    # Submit together so Ollama's scheduler reserves both configured resident
    # slots rather than treating the second refresh as a replacement workload.
    with ThreadPoolExecutor(max_workers=len(MODELS)) as pool:
        for model in pool.map(warm, MODELS):
            print(f"warm: {model}")


if __name__ == "__main__":
    main()

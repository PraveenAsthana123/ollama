#!/usr/bin/env python3
"""Preload the latency-sensitive Ollama models and keep them resident."""

import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml


def _default_models() -> list[str]:
    """Real fix, 2026-09-21: this used to hardcode "qwen3:1.7b,qwen2.5-coder:1.5b"
    as a plain string duplicate of config/token-tower.yaml's tiers.*.model
    values -- exactly the kind of drift this session already found and fixed
    twice elsewhere (token-tower.yaml's own cache flags vs its docs; this
    repo's checksummed config baseline exists specifically to catch this
    class of bug). Derive it from the real config's prewarm flags instead, so
    a future tier change or prewarm-policy change doesn't require remembering
    to also edit this separate hardcoded copy.

    tiers.strong.prewarm is deliberately false (VRAM: OLLAMA_MAX_LOADED_MODELS=2
    on this machine) -- NOT included here, and that's correct, not a gap."""
    config_path = Path(__file__).resolve().parents[1] / "config/token-tower.yaml"
    tiers = yaml.safe_load(config_path.read_text())["tiers"]
    return [spec["model"] for spec in tiers.values() if spec.get("prewarm")]


BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
_env_override = os.getenv("OLLAMA_WARM_MODELS")
MODELS = [m.strip() for m in _env_override.split(",") if m.strip()] if _env_override else _default_models()
KEEP_ALIVE = os.getenv("OLLAMA_WARM_KEEP_ALIVE", "30m")


def request(path: str, payload: dict) -> dict:
    if not (BASE_URL.startswith("http://") or BASE_URL.startswith("https://")):
        raise ValueError(f"refusing non-http(s) OLLAMA_BASE_URL: {BASE_URL!r}")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE_URL + path, body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as response:  # nosemgrep: dynamic-urllib-use-detected -- scheme validated above; BASE_URL is an operator-set env var, not remote input
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

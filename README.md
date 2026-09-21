# Ollama Control Tower

An operational stack for fast local Ollama inference, token limits, model routing,
cold-start control, LiteLLM, FreeLLMAPI, and repeatable model audits.

## What it controls

```text
Applications / Open WebUI / coding tools
                 |
          LiteLLM :4400
        fast | code | strong
                 |
      Ollama CUDA :11434 <--- legacy :11435 proxy
                 |
      GTX 1080 Ti / CUDA 12

FreeLLMAPI can use LiteLLM as one custom OpenAI-compatible provider and add
free cloud providers when the operator supplies their own API keys.
```

The Token Tower keeps requests bounded at a 4096-token working context and
prewarms the two latency-sensitive models. The strong 7B model is loaded only
when explicitly selected, preserving VRAM for the fast path.

## Measured result

On the reference GTX 1080 Ti host:

- CPU cold Qwen3 1.7B: 12.09 seconds to first token, 16.39 tokens/second.
- CUDA first initialization: 36.23 seconds of model load.
- CUDA warm Qwen3 1.7B: 0.61 seconds to first token, 127.78 tokens/second.
- Full catalog: 65 tags; 55 passed bounded load/inference checks, 2 failed,
  and 8 oversized models were inventoried without loading.
- Median generation speed across 51 tested text models: 80.41 tokens/second.

See [the runtime architecture](docs/ARCHITECTURE.md),
[the agent control tower](docs/AGENT_CONTROL_TOWER.md),
[the business agent map](docs/BUSINESS_AGENT_MAP.md),
[the token-efficiency pipeline](docs/TOKEN_EFFICIENCY_PIPELINE.md),
[cold-start operations](docs/COLD_START.md), and
[the audit summary](reports/model-audit-summary.json).

## Layout

- `scripts/control-tower` — status, catalog, warm, and audit entry point.
- `scripts/agent_control.py` — persistent agent states, budgets, approvals, and operator controls.
- `scripts/business_registry.py` — validates and queries business roles and workflows.
- `scripts/warm_models.py` — idempotent prewarm request for fast/code models.
- `scripts/audit_models.py` — bounded sequential model validation.
- `scripts/token_router.py` — budget, pruning, route, and exact-cache-key preparation.
- `config/token-tower.yaml` — context, output, residency, and routing policy.
- `config/agent-control.yaml` — trust, tool, MCP, retry, loop, and budget policy.
- `config/business-agent-registry.yaml` — domains, supervisors, roles, skills, tools, and approval gates.
- `config/litellm.yaml` — measured fast/code/strong aliases.
- `config/freellmapi.config.json` — local provider definition for FreeLLMAPI.
- `systemd/` — persistent CUDA server, prewarm timer, and legacy-port proxy.
- `reports/` — sanitized inventory and performance evidence.

## Install

Review paths in the unit files, then install as the current user:

```bash
python -m pip install -r requirements.txt
install -d "$HOME/.local/share/ollama-control-tower/scripts" "$HOME/.config/systemd/user"
install -m 755 scripts/*.py scripts/control-tower "$HOME/.local/share/ollama-control-tower/scripts/"
python scripts/build_model_index.py "$HOME/.local/share/ollama-control-tower/models" \
  "$HOME/.ollama/models"
install -m 644 systemd/* "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now ollama.service ollama-compat.socket ollama-prewarm.timer
systemctl --user start ollama-prewarm.service
```

The repository never contains model weights, provider keys, databases, raw
prompts, or encryption keys. Services bind to loopback by default.

Pass additional Ollama model directories to `build_model_index.py` to expose
multiple catalogs through one server. Duplicate tags from later directories
win. The script copies only small manifests and creates links to existing
content-addressed blobs.

## FreeLLMAPI

FreeLLMAPI is a separate upstream project. Point its declarative config at
`config/freellmapi.config.json`:

```bash
FREEAPI_CONFIG_PATH="$PWD/config/freellmapi.config.json"
```

The file registers this tower's LiteLLM endpoint as a local provider. Adding
cloud free tiers requires the operator's own provider keys through FreeLLMAPI.

## Sources

- Ollama: <https://github.com/ollama/ollama>
- LiteLLM: <https://github.com/BerriAI/litellm>
- FreeLLMAPI: <https://github.com/tashfeenahmed/freellmapi>

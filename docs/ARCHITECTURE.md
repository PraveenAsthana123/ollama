# Architecture

The broader supervisor, worker, MCP, and approval design is documented in
[Agent Control Tower](AGENT_CONTROL_TOWER.md). This page describes the model
runtime underneath that agent layer.

## Control Tower

The control plane owns health, inventory, model validation, compatibility, and
warm-state maintenance. It does not duplicate model blobs. Multiple existing
manifest catalogs can point to shared, immutable blob files from a unified
manifest index.

## Token Tower

The token policy prevents large default contexts from consuming VRAM and
increasing prompt-evaluation latency. Defaults are 4096 context tokens, bounded
output per tier, one parallel request on this 11 GB Pascal GPU, two resident
models, and a queue of 16.

MarkItDown or another extractor should turn PDF, DOCX, HTML, and spreadsheets
into Markdown before relevant sections are sent to a model. Extraction alone
does not guarantee lower token use; select only the necessary sections.

## Router

LiteLLM provides stable names:

| Alias | Model | Role | Warm |
|---|---|---|---|
| `fast` | `qwen3:1.7b` | general low-latency chat/tools | yes |
| `code` | `qwen2.5-coder:1.5b` | coding and structured work | yes |
| `strong` | `qwen2.5:latest` | higher-quality 7B work | on demand |

Port 11435 is a socket proxy to 11434 so legacy clients use the same GPU-backed
server and catalog. There is only one inference scheduler.

FreeLLMAPI sits above LiteLLM when multi-provider routing, quotas, cloud
failover, or prompt compression are needed. Local routing remains useful when
no cloud keys are configured.

## Hardware decision

Current vLLM GPU releases require a newer compute capability than the GTX 1080
Ti. Ollama CUDA 12 supports its compute capability 6.1, so Ollama is the GPU
fast path. The small local vLLM service remains CPU-only and is not part of the
low-latency default route.

## Security and data boundaries

All endpoints bind to loopback. The repository excludes keys, databases,
weights, raw prompts, and unredacted process environments. Wider network
exposure requires authentication and a separate review.

# Router-of-Routers Inference Control Tower

The inference policy composes six routing concerns without merging their trust
or availability assumptions:

```text
cache → context optimization → task/agent route → model tier
      → provider route (PAIR/local/free/paid) → quality evaluation
```

An exact or semantic cache hit returns immediately. A miss proceeds through
context pruning and classification, selects the fast, code, or strong tier, and
then chooses an eligible provider in configured order. A provider is eligible
only when policy enables it and the runtime health adapter reports the required
model and capacity. Paid inference additionally requires request-level consent.

```bash
scripts/control-tower inference plan \
  '{"query":"fix this parser","kind":"source"}' \
  '{"direct_ollama":{"healthy":true,"models":["qwen2.5-coder:1.5b"]}}'

scripts/control-tower inference evaluate \
  '{"provider":"direct_ollama","model":"qwen2.5-coder:1.5b"}' 0.91
```

Accepted output may enter cache and can enter Collective Memory only through
the verified-memory path. Output below the quality threshold receives at most
one escalation; another failure is rejected rather than silently returned.

## Current deployment boundary

Direct local Ollama is enabled. FreeLLMAPI, paid cloud, and NVIDIA PAIR are
disabled until their runtime health, credentials, quotas, and policy are
configured. The repository contains a FreeLLMAPI adapter configuration but does
not assume free-provider availability or capacity.

PAIR routes independent requests to an online node that owns the requested
model. It does not combine multiple machines to execute one request. PAIR's
Ollama-compatible proxy can occupy port `11434` while moving the local engine
behind it; therefore its endpoint must be copied from PAIR and deployment must
be coordinated with this repository's existing Ollama service and compatibility
proxy. The present GTX 1080 Ti deployment keeps PAIR disabled pending a
validated compatible-node setup.

The router produces a plan and never calls an external provider itself. A
runtime adapter performs health checks and inference, records AgentOps events,
honors Agent Control decisions, and returns output to the evaluator.

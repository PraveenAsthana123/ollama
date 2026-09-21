# Live operations checklist — 2026-09-21

This is a measured snapshot, not a claim that every architecture layer is in production.

| Area | Live result | Next requirement |
| --- | --- | --- |
| Portal / remote access | User service active; HTTP 200 locally; SSH tunnel from another computer documented | A managed private-network endpoint if tunnel-free access is required |
| Direct prompt / Claude preparation | Both portal POST paths returned a live `inference` result | Measure prompt quality and Claude token cost before making preparation the default |
| Cold start | SohamYoga watchdog was unloading prewarmed Qwen models every minute; protected-model override and four residency slots now accommodate Qwen fast, Qwen coder, embedding, and SohamYoga's small chat model | Observe over multiple timer cycles and large-model jobs |
| Token limits | Gateway now passes `num_ctx`, tier `num_predict`, and fast-tier `think=false` to Ollama | Measure input/output tokens from Ollama's native counters, not whitespace estimates |
| Context correctness | Supplied context now reaches Ollama; context requests bypass semantic cache | Add context pruning with quality checks and per-source limits |
| Cache correctness | Exact cache signed; semantic cache signed and now rejects numeric/identifier mismatch, with legacy points treated as misses; Qdrant was restarted and protected from Docker idle shutdown | Evaluate semantic false hits by task; isolate test collection from live collection |
| Monitoring / tracing | Event store and monitor health are live; `monitor health` reported 36 events and 13.89% error rate | Correlate portal requests, Claude preparation, gateway calls, Ollama timings, and agent sessions with one trace ID |
| Token analytics | 35 calls logged but input tokens reported as zero; cached/compressed attribution is incomplete | Ingest actual Ollama `prompt_eval_count` and `eval_count` into token metrics |
| Supervisor / dynamic agents | Supervisor and agent-control APIs exist; fleet snapshot reported zero active agents | Run an end-to-end supervised task with creation, handoff, verification, and cleanup |
| AgentOps / guardrails | AgentOps gate failed on success rate, error rate, P95 latency, one policy violation, and missing quality evidence | Establish real evaluations and investigate blocked/failed events before claiming production readiness |
| Self-healing | Ollama and portal restart on failure; prewarm timer and protected watchdog recover residency | Test outage/restart scenarios and record recovery time |
| Provider routing | Direct Ollama executes; PAIR/free/paid routes remain disabled or unimplemented | Enable only after independent capacity, privacy, and fallback tests |

Use portal `/diagnostics` for the current live values; this file records the initial audit and its open work.

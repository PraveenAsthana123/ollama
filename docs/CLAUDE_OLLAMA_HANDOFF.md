# Claude and Ollama operational handoff

## Verified state (2026-09-21)

- Ollama 0.30.8 is running as a user service at `127.0.0.1:11434`; 65 models are installed. A direct generate request and a request through `scripts/execution_gateway.py` succeeded.
- LiteLLM at `127.0.0.1:4400` returned a successful chat completion.
- The custom portal is served at `http://127.0.0.1:8795/`; `/run` returned a live Ollama answer through the execution gateway. `/api/health` checks the local endpoints without loading a model.
- The prewarm timer is active. `qwen3:1.7b` and `qwen2.5-coder:1.5b` became resident after prewarming. Cold loading was observed on the first request.
- Exact Redis and semantic Qdrant caches, a GPU scheduler, rate limiting, and security checks are present in the gateway. Cached or failed results must be distinguished from live inference by inspecting `decision` and `cache_hit`.

## Delegation contract

Use `control-tower status` before relying on local inference. The gateway now requires a private caller token: `EXECUTION_GATEWAY_TOKEN="$(cat ~/.local/state/ollama-control-tower/gateway.token)" control-tower delegate run 'short task title' '...output format...' --kind source --priority 1` for code or `--kind prose` for text. Never print the token. `control-tower delegate report` shows completion records. Confirm the JSON reports inference or a suitable cache hit and contains a nonempty response. Review and test the result. If the local model is unavailable, times out, or returns weak work, Claude should complete the task itself and report the fallback. Do not assume the CLI runs automatically; Claude must choose to call it.

## Remaining work, in priority order

1. **Measure token controls end to end.** The gateway now sends `num_predict`, `num_ctx`, and fast-tier `think=false`; it still reports whitespace-based output estimates rather than Ollama's native token counts. Capture `prompt_eval_count` and `eval_count` and evaluate answer quality at each tier.
2. **Evaluate context handling.** The gateway now sends bounded, delimited `--context` and bypasses semantic cache for context requests. Implement source-aware pruning and tests for long-context quality.
3. **Measure latency and quality by route.** Prewarming reduces cold starts but costs memory. Benchmark production tasks at cold and warm states, time to first token, total latency, answer quality, cache-hit rate, and GPU contention. Avoid keeping all 65 models loaded.
4. **Connect configured optimizers only after evaluation.** Context pruning and observation compression have components, but do not automatically optimize every gateway request. LLMLingua and LMCache adapters remain disabled; they need task-specific quality and latency benchmarks. Avoid semantic caching for personalized, time-sensitive, or security-sensitive answers without a strict scope/TTL.
5. **Correct stale architecture docs.** `docs/OLLAMA_FIRST_STRATEGY.md` still describes the real gateway/cache/scheduler as absent. Align it with verified runtime behavior.

The portal and Ollama are loopback-only. Access `http://127.0.0.1:8795/` on the same host or use an approved tunnel for another machine.

# Ollama-First Strategy

Real, verified state as of 2026-09-21 — every number below was measured
today, not estimated.

## The rule

```
Local Ollama is the default worker for every text/embedding task this
platform controls. Cloud/paid models are never the default -- only an
explicit, deliberate escalation.
```

## What this rule actually covers (and what it doesn't)

**Covers**: job-portal's own application code (resume matching, resume-gap
suggestions, SWOT generation, the job-discovery agent, all real embed/chat
calls) and control-tower's own routing config.

**Does not cover**: Claude Code's own task execution in this development
session. There is no mechanism in this codebase for a Claude Code session to
delegate its own assigned work to a local model instead of processing it
directly -- that would require a different system architecture (an
autonomous supervisor dispatching sub-tasks to Claude only on escalation,
which is the *target* architecture described in the "Ollama Local AI Super
Platform" action prompt, not something built or claimed as built here).
Stating this plainly rather than implying a capability that doesn't exist.

## Verified compliance, job-portal

- 100% of job-portal's AI features (matching, resume suggestions, SWOT,
  agent plan/advise) call local Ollama only. Zero paid API calls anywhere
  in `job-portal-prototype` or `job-portal-praveen` this entire project.
- `inference-control-tower.yaml`: `direct_ollama.enabled: true`; `pair`,
  `free_cloud`, `paid_cloud` all `enabled: false` by explicit config, not
  by omission.

## Real performance data backing this strategy (measured today)

| Metric | Value | Source |
|---|---|---|
| Cold chat load time | 49.38s (98.6% of the 50.07s total) | `bench_production_models.py` |
| Warm chat throughput | 35-40 tokens/sec | `bench_production_models.py` |
| Cold embed | 2.11s | `bench_production_models.py` |
| Warm embed (cached) | 0.001s (2,446x speedup) | Redis exact-cache, verified |
| Model residency right now | 0 hot / 65 installed | `model_residency.py` |

## What actually makes Ollama-first effective, in priority order

1. **`keep_alive: 30m`** (shipped) — eliminates the 98.6% cold-load cost for
   any request arriving within 30 minutes of the last one.
2. **Redis exact-cache on `embed()`** (shipped) — eliminates the call
   entirely for exact-duplicate text, verified 2,446x.
3. **Real benchmark + residency visibility** (shipped, this doc) — you can't
   tell if "Ollama-first" is actually fast without measuring load vs.
   generation time separately; a single wall-clock number hides which one
   to fix.
4. **Model-swap discipline** (documented in
   `~/.claude/projects/-mnt-deepa-chatgpt/memory/feedback_verify_before_model_swap.md`)
   — two real attempts to move to a faster/smaller model (`qwen3:1.7b`,
   `vLLM`/`Qwen2.5-0.5B`) both failed real-task testing. Ollama-first only
   stays "effective" if the local model actually gets the task right;
   speed without correctness isn't a win.

## Explicitly NOT done (real gaps, not hidden)

- No GPU semaphore / queue-priority system — not built, because job-portal's
  actual usage pattern is sequential, not concurrent; there is no measured
  contention problem to solve yet. Building one now would be speculative.
- No semantic cache (only exact-match Redis cache exists).
- No cost/token budget enforcement beyond what `control-tower tokens` reports.

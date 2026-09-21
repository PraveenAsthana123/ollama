# Router Federation

Router Federation catalogs routing products by architectural role instead of
treating every project as an interchangeable gateway. The catalog separates:

- provider gateways and compatibility gateways;
- learned and semantic routers;
- coding clients and user interfaces;
- prompt compression, response caching, and KV caching;
- the Control Tower's own policy router.

Only provider and compatibility gateways participate in gateway selection.
Compressors and caches run at their own pipeline stages; clients remain clients.

```bash
control-tower routers validate
control-tower routers list
control-tower routers list --kind gateway
control-tower routers select \
  '{"litellm":{"healthy":true,"quality":0.9,"latency_ms":80,"cost_per_1k":0,"privacy":1,"fallback_success":0.95,"gpu_efficiency":0.8}}' \
  --require openai_api,fallback
```

Selection first requires that an adapter is enabled, installed, healthy, outside
its circuit-breaker cooldown, and supplies every requested capability. Remaining
candidates receive a configurable score for quality, latency, cost, privacy,
fallback success, and GPU efficiency. The output includes the selected adapter,
ordered fallbacks, measured scores, and endpoint.

The catalog contains LiteLLM, Claude Code Router, Bifrost, Portkey, Helicone,
TensorZero, OpenRouter, Kiro Gateway, Kiroxy, RouteLLM, Semantic Router,
Continue, Aider, Open WebUI, LLMLingua, GPTCache, LMCache, and the custom policy
router. Only the already deployed LiteLLM gateway and custom policy router are
enabled. External entries remain disabled until installation, credentials,
health, security, and representative benchmarks are validated.

Kiro itself is an agentic coding environment. Compatibility gateways around it
do not become trusted generic routers automatically. Credential pooling and
refresh are disabled until a secrets and provider-terms review is complete.

Router scores are meaningful only when measurements use the same tasks, models,
hardware, concurrency, and sampling procedure. Store benchmark summaries and
trace identifiers; never store provider credentials in benchmark JSON.

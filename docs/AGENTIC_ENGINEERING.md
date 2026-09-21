# Agentic Engineering Lifecycle

The platform tracks 25 engineering stages as a verifiable lifecycle. Each stage
is classified as `implemented`, `contract`, `external`, or `planned`, and every
implemented stage must point to repository evidence that exists.

```text
Engineering → Harness → Factory → Registry → Decomposition → Planning
→ Creation → Assignment → Supervisor/Worker → Collaboration → Handoff
→ A2A → MCP → Memory → Model Router → Agent Router → Tool Router
→ Token Optimization → Evaluation → AgentOps → Observability
→ Security → Human Approval → FinOps → Control Tower
```

Run the audit after architecture or implementation changes:

```bash
scripts/control-tower platform --strict
```

The JSON report includes every stage, its evidence, status totals, implementation
percentage, and open production gates. Strict mode exits unsuccessfully when a
stage uses an invalid status, an implemented stage has no evidence, a referenced
artifact is missing, or the ordered 1–25 lifecycle is incomplete.

## Current boundary

The repository implements the local control-plane foundations: registry,
harness policy, agent state, supervisor scheduling, model/agent/tool routing,
token optimization, monitoring, guardrails, approvals, FinOps metrics, and the
unified CLI. Some layers intentionally remain contracts or external services.

The production gates are explicit:

1. Runtime adapters must enforce harness and Agent Control decisions inside
   each selected worker runtime.
2. A2A communication needs authenticated identities, ACLs, bounded messages,
   correlation, replay protection, and tracing.
3. Collective memory needs scope, provenance, retention, deletion, access
   control, and stale-memory evaluation.
4. Continuous evaluation needs representative datasets, task and trace graders,
   release thresholds, and regression reporting.
5. Selected MCP, telemetry, cache, and cloud backends must be deployed and
   validated in the target environment.

This distinction prevents configuration, diagrams, or adapter contracts from
being reported as running production integrations.

## Engineering loop

For every new capability:

1. Define its contract, owner, inputs, outputs, limits, and failure behavior.
2. Add the smallest enforceable implementation and evidence artifact.
3. Test success, denial, timeout, retry, and incomplete-evidence behavior.
4. Emit correlated monitoring and token metrics.
5. Add security and human approval boundaries where impact requires them.
6. Change lifecycle status only when the evidence matches the definition.
7. Run the strict platform audit and complete repository tests.

Learning repositories can inform patterns, but they are not runtime
dependencies. Frameworks such as LangGraph, MCP servers, AgentOps backends, and
cloud services remain replaceable behind the platform contracts.

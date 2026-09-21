# Fleet Control View

The fleet command joins durable Agent Control records with recent Monitoring
events into one read-only operational snapshot:

```bash
control-tower fleet
control-tower fleet --since-seconds 3600 --stale-seconds 300
```

Each row shows an agent's parent and children, session, worker, model, status,
priority, trust tier, token and cost budgets, steps, failures, handoffs, P95
latency, and whether its heartbeat is stale. Rows are ordered by operator
priority. The fleet totals summarize status, token and cost use, stalled agents,
failures, and handoffs.

Create an agent with hierarchy and priority, or change priority while it runs:

```bash
control-tower agent create coder-1 --parent-agent-id supervisor-1 \
  --session-id session-42 --priority 8 --worker openhands
control-tower agent priority coder-1 9
control-tower agent pause coder-1
```

The command reports control intent and telemetry; a runtime adapter still must
observe checkpoints to pause or terminate actual work. A stale agent is a
diagnostic signal, not proof that its process died. The view does not send
commands or automatically kill unrelated processes.

This closes the fleet-visibility gap highlighted by Flightdeck, AgentMonitor,
and multi-agent command-center patterns while retaining the existing Control
Tower's agent state, policy checks, replay, and quality gates as separate
components.

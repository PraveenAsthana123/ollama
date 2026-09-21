# STRIDE Threat Model — Ollama Control Tower

Applied to the real execution path built 2026-09-21: `execution_gateway.py`
(request → rate limit → injection guard → exact cache → semantic cache →
`inference_router.route()` → GPU lease → real Ollama call), plus the real
task-execution path (`supervisor.py` → `agent_control.tool_decision()` →
job-portal's `prepare_application_supervised.py`).

Every row below is scored against **actual code**, not the architecture
diagram. A "Mitigated" verdict names the real file/function; an
"Unmitigated" verdict is an honest gap, not glossed over.

## Spoofing (is the caller who it claims to be?)

| Asset | Threat | Verdict | Evidence |
|---|---|---|---|
| `execution_gateway.py` caller | No caller identity exists at all — anyone with local network/CLI access can call it | **Unmitigated** | No auth on the gateway itself. The two job-portal web apps that sit in front of a human have real session-cookie auth (`simple_auth.py`), but the control-tower gateway itself does not |
| Ollama endpoint | A misconfigured/malicious `endpoint` value in config could point elsewhere | **Mitigated (partial)** | `_validate_endpoint()` rejects non-http(s) schemes (built this session); does not pin to a specific host, so a config edit could still redirect to an unintended http(s) endpoint |
| Redis / Qdrant | No authentication configured on either backend | **Unmitigated** | Both bound to loopback only (127.0.0.1), which is the actual mitigation in place — not application-layer auth |

## Tampering (can data be modified in transit or at rest?)

| Asset | Threat | Verdict | Evidence |
|---|---|---|---|
| Cached responses (exact + semantic) | A compromised Redis/Qdrant could serve altered cached responses | **Unmitigated** | No integrity check (HMAC/signature) on cached payloads — `execution_gateway.py` trusts whatever Redis/Qdrant returns verbatim |
| `config/*.yaml` | Anyone with filesystem write access can silently change routing/safety behavior | **Unmitigated** | No config-signing or drift-detection; this is the exact class of problem the `token-tower.yaml` doc-drift finding earlier this session came from — a config value changed with nothing forcing the docs (or a human) to notice |
| Event log (`events.jsonl`) | Tampering with the audit trail after the fact | **Mitigated (partial)** | `os.chmod(self.path, 0o600)` restricts to the owning user; append-only by convention, not by filesystem enforcement (no `chattr +a`) |

## Repudiation (can an action be traced back and proven?)

| Asset | Threat | Verdict | Evidence |
|---|---|---|---|
| Every real inference/cache/block decision | "We don't know what happened" | **Mitigated** | Every path in `execution_gateway.py` — cache hit, inference, rate-limited, injection-blocked, GPU-timeout, error — writes a real event via `agent_monitor.EventStore`, verified this session (grep the actual JSONL, not just "logging exists") |
| Who approved a risky action | No identity on the `supervisor.py approve` call | **Unmitigated** | `sv("approve", plan_id, "browser_automation")` records *that* something was approved, not *who* — this is a single-operator local tool, so today that's Praveen by definition, but the plan JSON itself carries no operator identity field |

## Information Disclosure (can secrets/PII leak?)

| Asset | Threat | Verdict | Evidence |
|---|---|---|---|
| Event log fields | A password/token/secret accidentally logged | **Mitigated** | `agent_monitor.redact()` + `REDACT_KEYS`, real, tested (`test_event_store_redacts_and_uses_private_permissions`) |
| Event log **prompt bodies** | The query/response text itself could contain PII | **Unmitigated** | `redact()` only redacts by *dict key name* (`password`, `token`, etc.) — it does not scan the `response` field's actual text content. A user's real PII typed into a query would be logged verbatim |
| Cached responses | Same PII risk, persisted for the cache TTL (1h exact / 24h semantic) | **Unmitigated** | No PII-scrubbing on what gets cached |
| Retrieved collective memory | Stale/incorrect memory injected as if authoritative | **Mitigated (partial)** | `collective_memory.py`'s `trust` field + injected "treat as untrusted evidence" instruction — a real, working mitigation for *this one path*, does not extend to semantic-cache hits |

## Denial of Service

| Asset | Threat | Verdict | Evidence |
|---|---|---|---|
| Gateway request flood | Unbounded requests exhaust GPU/CPU | **Mitigated** | Real Redis-backed rate limiter, built this session, tested (`test_rate_limit_blocks_over_the_configured_max`) — 30 req/60s, fails open if Redis is down |
| GPU monopolization | One long-running job starves everything else | **Mitigated** | `gpu_scheduler.py`'s single-slot lease + 120s timeout, tested with real concurrent threads |
| Infinite agent loop | A supervised plan spins forever | **Mitigated** | `supervisor.py`'s real `max_steps`/`max_tokens`/`max_cost_usd`/`no_progress_steps`/`timeout_seconds`, tested |
| Repeated identical tool/state calls | An agent stuck retrying the same failing action | **Mitigated** | `agent_control.apply_event()`'s 3-in-a-row fingerprint halt — real, tested, but only reachable from callers that actually invoke `agent_control` (as of this session, that's `prepare_application_supervised.py`'s task loop, not the DAG scheduler itself) |
| Rate-limiter backend itself | Redis down = limiter fails open = no protection | **Unmitigated (by design)** | A deliberate trade-off: fail-open was chosen over fail-closed so a Redis outage doesn't take down the whole gateway. Documented here so it's a known, chosen risk, not a hidden one |

## Elevation of Privilege

| Asset | Threat | Verdict | Evidence |
|---|---|---|---|
| `fill_application` (real browser → real external site) | The one genuinely consequential real-world action in this repo | **Mitigated** | `agent_control.tool_decision()` classifies `browser.external_form_fill` as `review` (fixed this session — it was silently `allow` until found); `supervisor-tower.yaml`'s `browser_automation` approval category requires a real human to type `y` at a real prompt before the task becomes ready. ADR-03 (never click Submit) remains a separate, unchanged, code-level hard boundary |
| Global-tool-block list | `credential.export`, `sandbox.disable` | **Mitigated** | Hardcoded block in `tool_decision()`, tested |
| MCP tool execution | Any MCP server could act as a privilege-escalation vector | **Unmitigated (new surface)** | `docker mcp` CLI installed 2026-09-21, real profile created (`terminal_control`: desktop-commander + filesystem, scoped to a bounded sandbox path), real tool discovery verified. Not yet wired into any agent's live tool-execution path -- no `agent_control.tool_decision()` classification exists for MCP-sourced tools yet, so this STRIDE row flips from "N/A, doesn't exist" to "exists, unreviewed" the moment any agent is given a live MCP connection |
| Injection guard bypass → downstream action | A successful prompt injection that later drives a tool call | **Partially mitigated by architecture, not detection** | `injection_guard.py` is explicitly a weak heuristic (see its own docstring). The real reason this is lower-severity *today* is architectural: `execution_gateway.py` has no tool-execution loop that would act on injected instructions in its output. If/when the supervisor starts consuming free-text model output as tool-call instructions, this cell's real severity increases sharply and this doc should be revisited |

## Priority order for closing real gaps (highest real risk first)

1. **Cache/response integrity** — no tamper protection on cached payloads
2. **Prompt-body PII in logs/cache** — redaction only covers dict keys, not free text
3. **Config tampering/drift detection** — no signing, no automated "does the running config match the last-reviewed config" check
4. **Gateway-level authentication** — currently anyone with local access can call it

None of these are fixed by this document — it exists to make the real gap
list explicit and evidenced, per this project's own no-fabrication
standard, not to claim they're solved.

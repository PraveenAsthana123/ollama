# GitHub feature review — 2026-09-21

The local stack already has a gateway, agent-control modules, a portal, Redis/Qdrant caches, and CI security checks. Add external systems only when they solve a measured gap. Candidate capabilities below are verified from the projects' own repositories; none is claimed as deployed here.

| Priority | Candidate | Specific value here | Pilot gate |
| --- | --- | --- | --- |
| 1 | [Stacklok ToolHive](https://github.com/stacklok/toolhive) | MCP registry/gateway with isolated server runtime, access policies, auditing, OpenTelemetry, and semantic tool search to reduce MCP schema tokens | Pilot one read-only MCP server; measure discovery tokens, latency, and authorization |
| 1 | [IBM ContextForge](https://github.com/IBM/mcp-context-forge) | MCP/A2A/API federation, tool discovery, routing, and tracing | Compare with ToolHive on the same server; adopt one gateway, not two overlapping control planes |
| 2 | [Langfuse](https://github.com/langfuse/langfuse) | Trace and evaluation UI for model, tool, and agent spans | Export redacted OpenTelemetry events; verify privacy, overhead, and self-host resource cost |
| 2 | [Microsoft LLMLingua](https://github.com/microsoft/LLMLingua) / [CoACT](https://github.com/THU-Agent/CoACT) | Prompt or tool-observation compression | Benchmark representative tasks for token savings, correctness, compression latency, and recoverability before enabling |
| 3 | [Paperclip](https://github.com/paperclipai/paperclip) | Agent org charts, goals, budgets, task review, and governed work assignment | Try a small agent team; avoid duplicating the local supervisor until its own end-to-end quality gate passes |
| 3 | [OpenClaw](https://github.com/openclaw/openclaw) | Multi-channel personal agent gateway and pluggable harness | Use only if chat/channel access is a product requirement; it is not a faster Ollama inference engine |
| 3 | [Wazuh](https://github.com/wazuh/wazuh) | Host security telemetry, detection, response, SIEM/XDR-style dashboard | Pilot on a separate resource budget; distinguish endpoint security events from agent quality metrics |

The host already runs a healthy `sohamyoga-contextforge` container on loopback port 4444. This is a shared deployment, not yet a verified Ollama Control Tower integration. Test one read-only tool path through it before adding a second MCP gateway.

Security evidence already present: [Semgrep](https://github.com/semgrep/semgrep) runs SAST in CI; [Syft](https://github.com/anchore/syft) generates a CycloneDX SBOM; [Grype](https://github.com/anchore/grype) scans that SBOM. [ZAP API Scan](https://github.com/zaproxy/action-api-scan) is an appropriate DAST candidate for the portal, but a portal-specific report has not been produced. [Trivy](https://github.com/aquasecurity/trivy) is installed locally and could consolidate vulnerability, secret, and misconfiguration checks after comparing findings with the existing pipeline. A cryptographic bill of materials (CBOM) is not yet generated. Security scanning and SIEM/XDR/SOAR should appear in the portal as evidence-backed functions, not as implied coverage merely because a tool is installed.

Near-term work that likely saves more time than installing another platform: ingest native Ollama token counts; preserve small-model residency across every watchdog; isolate semantic-cache tests from live Qdrant; add correlated trace IDs; run one real supervised agent task with measured quality; and fix the failing AgentOps gate. The portal's `/capabilities` page is the honest showcase, while `/diagnostics` shows live conditions.

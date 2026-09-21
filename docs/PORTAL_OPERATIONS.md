# Ollama portal and remote access

The portal is a persistent user service at `http://127.0.0.1:8795/`. It remains running after logout because user lingering is enabled. The systemd service restarts on failure. `systemctl --user status ollama-portal.service` checks it; `/api/health` checks Ollama and LiteLLM without loading a model.

From another computer on the same network, open a secure SSH tunnel:

```bash
ssh -N -L 8795:127.0.0.1:8795 praveen@192.168.1.171
```

Then browse `http://127.0.0.1:8795/` on that computer. The tunnel must stay open while browsing. The portal stays bound to host loopback so its prompt and operations endpoints are not exposed directly over the LAN. If the host LAN address changes, replace `192.168.1.171` with its current address.

The **Prompt terminal** supports text, code, and bounded jobs. Direct mode routes to local Ollama; Claude-prepared mode asks the local Claude CLI to rewrite the task and then sends that prompt to Ollama. Claude-prepared mode consumes Claude usage. The **Operations terminal** accepts only the listed read-only commands; it is not an arbitrary shell. Diagnostics reports service state, model residency, recent blocked/failed events, and known implementation gaps.

For cold starts, `ollama-prewarm.timer` refreshes the fast and coding models every 5 minutes. The embedding model and the shared SohamYoga `llama3.2:1b` workload need two more slots; `systemd/ollama-residency.conf` sets `OLLAMA_MAX_LOADED_MODELS=4`. The Control Tower's three model files total about 2.6 GB on disk, with additional runtime/context memory. Check actual GPU memory and model residency after deployment. Other large-model workloads can still evict them.

The shared SohamYoga watchdog previously unloaded both warmed Qwen models one minute after prewarming because it knew only its own protected models. Its `app/idle_monitor.py` now accepts `OLL_PROTECTED_MODELS`; the one-line change is preserved in `integrations/soham-idle-monitor.patch`. `systemd/soham-watchdog-protected-models.conf` protects the fast, code, and embedding models in that watchdog's user service. The watchdog's own idle cleanup continues for other models. This cross-project integration must be retained if SohamYoga is redeployed.

The Docker idle monitor previously stopped the standalone `ollama-control-tower-qdrant` container. It is now listed in `~/.config/docker-idle-monitor/config.json` under `protected_containers`, and `/healthz` passed after restart. Keep that protection while the semantic cache is enabled. The persistent Redis service must also remain available for exact caching and GPU scheduling.

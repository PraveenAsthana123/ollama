# Cold-start control

Cold starts have two costs: CUDA runtime initialization and model loading.
Changing model families can also evict a resident model. The tower addresses
this with a persistent user service, a 30-minute keep-alive, four resident
model slots on this shared host, and a timer that concurrently refreshes the
fast and code models every 5 minutes. Other slots serve semantic-cache
embeddings and the shared SohamYoga chat model when used.

The SohamYoga watchdog shares this Ollama daemon and previously unloaded the
prewarmed models every minute. Its `OLL_PROTECTED_MODELS` service override now
protects them; see `docs/PORTAL_OPERATIONS.md`. Check that override as well as
the prewarm timer when residency unexpectedly drops.

Check current residency:

```bash
scripts/control-tower status
```

Warm immediately:

```bash
scripts/control-tower warm
```

The first start after boot or a driver update can still take tens of seconds.
After prewarming, the measured Qwen3 1.7B time to first token was 0.61 seconds.

Do not prewarm every model. Doing so causes eviction, disk traffic, and worse
latency. Keep two small frequently used models resident and load large models
only for explicit quality-sensitive tasks.

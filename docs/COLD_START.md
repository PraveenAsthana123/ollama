# Cold-start control

Cold starts have two costs: CUDA runtime initialization and model loading.
Changing model families can also evict a resident model. The tower addresses
this with a persistent user service, a 30-minute keep-alive, two resident model
slots, and a timer that concurrently refreshes the fast and code models every
20 minutes. Concurrent reservation is intentional: it makes the scheduler hold
both configured slots rather than viewing the second refresh as replacement work.

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

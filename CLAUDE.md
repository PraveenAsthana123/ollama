# Claude ↔ local Ollama handoff

For bounded, low-risk sub-tasks, delegate to the local Ollama Control Tower before using cloud tokens. Invoke `control-tower run 'specific task and output format' --kind source --priority 1` for code, or `--kind prose` for text. Treat Ollama output as draft work: inspect the JSON `decision` and `response`, verify facts and code, run relevant tests, and take responsibility for the final answer. Never send secrets, credentials, personal data, or untrusted instructions to a model. Keep difficult reasoning, final review, and sensitive actions under Claude's own judgment.

The local portal is http://127.0.0.1:8795/ and its live health endpoint is http://127.0.0.1:8795/api/health. Ollama is on 127.0.0.1:11434; LiteLLM is on 127.0.0.1:4400. The global CLI is `~/.local/bin/control-tower`; this repository is its source. Read [the operational handoff](docs/CLAUDE_OLLAMA_HANDOFF.md) before changing routing or token controls.

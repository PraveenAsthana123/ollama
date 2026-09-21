# Collective Memory

Collective Memory stores reusable evidence outside the active model context and
retrieves only a small relevant subset. It is governed shared state, not an
unbounded transcript or a source of executable instructions.

Memory is isolated into `task`, `agent`, `team`, and `global` scopes. Every item
has an owner, provenance, namespace, trust level, content hash, tags, creation
time, and expiration. Identical content within a scope and namespace is
deduplicated. Retrieval requires an explicit allowed-scope list and is bounded
by both result count and estimated tokens.

```bash
scripts/control-tower memory put team payments \
  "Invoice reconciliation requires account matching" \
  --owner finance-agent --provenance task-42 --actor supervisor \
  --trust verified --tags invoice,reconciliation

scripts/control-tower memory search "invoice matching" \
  --scopes task,agent,team --limit 5 --token-budget 500

scripts/control-tower memory stats
scripts/control-tower memory forget MEMORY_ID --actor supervisor
```

The SQLite database defaults to
`~/.local/state/ollama-control-tower/memory/collective.db` with file mode `0600`.
Writes and deletions create audit entries. Expired memories stay excluded from
retrieval until a retention job purges them. Global writes fail closed because
they require an approval adapter; broad persistent memory should never be
created from an ordinary agent command.

Every retrieved item is labeled as untrusted evidence. Agents must verify it
before action because persistent memory can become stale, incorrect, or contain
prompt injection. Trust labels describe provenance confidence; they do not turn
stored text into system instructions.

This local foundation can later use a vector or graph backend behind the same
scope, provenance, retention, deletion, and audit contract. External memory
products remain optional and require independent deployment validation.

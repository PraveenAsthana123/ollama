# MCP Gateway

Real `docker/mcp-gateway` CLI, installed 2026-09-21 -- closes the "MCP
Gateway: EXTERNAL / not runtime-integrated" gap the external audit flagged
repeatedly. This is the official Docker-maintained implementation
(1,579+ stars), not a third-party clone.

## What's real right now

- CLI plugin installed at `~/.docker/cli-plugins/docker-mcp` (v0.43.3,
  pre-built Linux binary -- this machine's Go 1.22.5 is below the 1.24+
  the repo needs to build from source, so the release binary was used
  instead of `make docker-mcp`)
- Real catalog pulled: `mcp/docker-mcp-catalog`
- Real profile created: `terminal_control` (from the official
  `terminal-control` starter template) with two real servers:
  `desktop-commander` and `filesystem`
- Both servers scoped to a bounded sandbox path
  (`/mnt/deepa/chatgpt/security-tools/mcp-demo-sandbox`), not broad
  filesystem access -- `desktop-commander` specifically has real
  terminal-command execution capability, so this scope is a deliberate
  safety boundary, not an oversight
- Real tool discovery verified: `docker mcp tools ls`/`count` against the
  live gateway returns 8 real tools (the gateway's own dynamic
  tool-management meta-tools: `mcp-find`, `mcp-exec`, `mcp-add`, etc.)

## What's NOT done (honest, not glossed over)

- Not running as a persistent service -- each `docker mcp` invocation
  starts/stops the gateway process for that call. No systemd unit exists
  for it yet.
- Not wired into `agent_control.py`'s tool-risk classification --
  `tool_decision()` has no MCP-specific category yet. Per the STRIDE
  threat model, this is a real, currently-unmitigated privilege-escalation
  surface the moment any agent gets a live MCP connection, not before.
- Not connected to any agent's actual reasoning loop -- this is
  infrastructure verified to work, not yet a capability any real workflow
  in this repo calls.

## Non-Docker-Desktop setup (this machine runs plain Docker CE, not Desktop)

```bash
export DOCKER_MCP_IN_CONTAINER=1
docker mcp feature enable profiles
docker mcp catalog pull mcp/docker-mcp-catalog
docker mcp template use terminal-control
docker mcp profile config terminal_control \
  --set 'desktop-commander.paths=["/path/to/a/bounded/sandbox"]'
docker mcp profile config terminal_control \
  --set 'filesystem.paths=["/path/to/a/bounded/sandbox"]'
docker mcp tools ls --gateway-arg --profile=terminal_control
```

Real error hit and fixed along the way: `--set key=value` with a plain
string for `paths` fails validation ("has type string, want..."). The
`--set` flag's own help text says the value may be JSON for typed
fields -- a JSON array (`["..."]`) is required, not a bare path string.

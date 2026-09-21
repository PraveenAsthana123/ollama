#!/usr/bin/env python3
"""
Ollama Portal -- real status/benchmark/activity dashboard for this
machine's local Ollama instance. Stdlib-only (http.server), same pattern as
job-portal-prototype -- no new framework, minimal footprint.

Every number on this page is read live from a real source:
  - model residency: Ollama's own /api/ps + /api/tags
  - token metrics: control-tower's real token_metrics.py (fed by
    ollama_client.py's real telemetry integration)
  - recent activity: control-tower's real events.jsonl
  - benchmark: runs bench_production_models.py live on demand (real
    cold/warm timing against the actual production models), not cached
    canned numbers

Usage:
  python3 app.py --port 8795
"""

from __future__ import annotations

import argparse
import html
import hmac
import json
import os
import secrets
import shlex
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

CONTROL_TOWER = Path(__file__).resolve().parents[1]
EVENTS_LOG = Path.home() / ".local/state/ollama-control-tower/monitor/events.jsonl"
# The portal's own systemd service runs under /usr/bin/python3 with a
# minimal PATH -- a bare "python3" subprocess call resolves to whatever's
# first on that PATH, which does NOT have redis/pyyaml/qdrant-client
# installed (confirmed: /usr/bin/python3 raises ModuleNotFoundError on
# redis). control-tower's own global CLI launcher activates this exact venv
# for the same reason -- use it explicitly rather than relying on ambient
# PATH resolution, which happened to work before only because the two
# pre-existing subprocess calls (model_residency.py, bench_production_models.py)
# are stdlib-only.
CONTROL_TOWER_PYTHON = "/home/praveen/venv-ardupilot/bin/python3"
ZAP_REPORT = CONTROL_TOWER / "reports/zap-portal-baseline.json"

BASE_CSS = """
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0; color: #1a1a1a; background: #f7f7f8; }
  .topbar { background: #14213d; color: #fff; padding: 0.75rem 1.25rem; }
  .topbar a { color: #fff; text-decoration: none; font-weight: 600; }
  main { padding: 1.5rem 2rem; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.4rem; }
  h3 { margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; background: #fff; margin-top: 0.5rem; }
  th, td { text-align: left; padding: 0.5rem 0.7rem; border-bottom: 1px solid #eee; font-size: 0.88rem; }
  th { background: #fafafa; color: #555; }
  .kpi-row { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .kpi { background: #fff; border: 1px solid #e2e2e6; border-radius: 8px; padding: 1rem 1.25rem; min-width: 130px; }
  .kpi .num { font-size: 1.6rem; font-weight: 700; }
  .kpi .label { font-size: 0.8rem; color: #666; }
  .hot { color: #146c2e; font-weight: 600; }
  .cold { color: #888; }
  .note { background: #fff3a3; color: #5c4b00; padding: 0.6rem 1rem; border-radius: 6px; font-size: 0.85rem; margin-bottom: 1rem; }
  button, .btn { background: #1a5fb4; color: #fff; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; font-size: 0.9rem; text-decoration: none; display: inline-block; }
  .fail { color: #a01818; }
"""
CSRF_TOKEN = secrets.token_urlsafe(32)

TERMINAL_COMMANDS = {
    "help": None,
    "status": ["scripts/control-tower", "status"],
    "residency": ["python3", "scripts/model_residency.py"],
    "tokens": ["scripts/control-tower", "tokens"],
    "fleet": ["scripts/control-tower", "fleet"],
    "agentops": ["scripts/control-tower", "agentops", "gate"],
    "diagnose": ["python3", "scripts/diagnose_stack.py"],
    "delegations": ["scripts/control-tower", "delegate", "report"],
}


def terminal_command(command: str) -> str:
    """A read-only operations console, never a general-purpose shell."""
    argv = shlex.split(command)
    if len(argv) != 1 or argv[0] not in TERMINAL_COMMANDS:
        return "Unknown command. Type help to list supported operations."
    if argv[0] == "help":
        return "Available commands: " + ", ".join(TERMINAL_COMMANDS)
    cmd = TERMINAL_COMMANDS[argv[0]]
    full_cmd = [CONTROL_TOWER_PYTHON, *cmd[1:]] if cmd[0] == "python3" else cmd
    completed = subprocess.run(full_cmd, capture_output=True, text=True, cwd=CONTROL_TOWER, timeout=30)
    return (completed.stdout or completed.stderr or f"Exit status {completed.returncode}")[:20000]


def prepare_task(query: str, task_type: str, route: str) -> tuple[str, str]:
    if task_type not in {"text", "code", "job"} or route not in {"direct", "claude"}:
        raise ValueError("Unsupported task type or route")
    if not query or len(query) > 12000:
        raise ValueError("Prompt must contain 1–12000 characters")
    kind = "source" if task_type == "code" else "prose"
    prompt = query
    if task_type == "job":
        prompt = "Complete this bounded job. State the result and any assumptions clearly.\n\n" + query
    if route == "claude":
        instruction = (
            "Rewrite the following request as a concise, self-contained task for a local Ollama model. "
            "Preserve requirements and output format. Return only the rewritten task, with no preamble. "
            "Do not execute the task.\n\nRequest:\n" + prompt
        )
        completed = subprocess.run(
            ["claude", "-p", instruction, "--max-turns", "1"],
            capture_output=True, text=True, cwd=CONTROL_TOWER, timeout=90,
            env={**os.environ, "PATH": f"/home/praveen/.local/bin:{os.environ.get('PATH', '')}"},
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            raise RuntimeError("Claude prompt preparation failed; use Direct Ollama or inspect the Claude CLI")
        prompt = completed.stdout.strip()[:16000]
    return prompt, kind


def run_json(cmd: list[str]) -> dict:
    full_cmd = [CONTROL_TOWER_PYTHON, *cmd[1:]] if cmd[0] == "python3" else cmd
    env = os.environ.copy()
    if "scripts/execution_gateway.py" in cmd or "scripts/delegate.py" in cmd:
        token_path = Path.home() / ".local/state/ollama-control-tower/gateway.token"
        if not token_path.exists():
            token_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(token_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as token_file:
                    token_file.write(secrets.token_urlsafe(32))
            except FileExistsError:
                pass
        env["EXECUTION_GATEWAY_TOKEN"] = token_path.read_text().strip()
    result = subprocess.run(full_cmd, capture_output=True, text=True, cwd=CONTROL_TOWER, timeout=180, env=env)
    return json.loads(result.stdout) if result.stdout.strip() else {"error": result.stderr}


def layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)} - Ollama Portal</title>
<style>{BASE_CSS}</style></head>
<body>
<div class="topbar"><a href="/">Ollama Portal</a></div>
<main><h1>{html.escape(title)}</h1>{body}</main>
</body></html>"""


def kpi(num, label) -> str:
    return f'<div class="kpi"><div class="num">{num}</div><div class="label">{html.escape(str(label))}</div></div>'


def health_status() -> dict:
    """Cheap, live checks; this endpoint never loads a model."""
    services = {}
    for name, url in (
        ("ollama", "http://127.0.0.1:11434/api/version"),
        ("litellm", "http://127.0.0.1:4400/health/liveliness"),
    ):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # nosemgrep: dynamic-urllib-use-detected -- URLs are the two fixed loopback literals above, never user input
                services[name] = {"ok": response.status == 200, "http_status": response.status}
        except Exception as exc:
            services[name] = {"ok": False, "error": type(exc).__name__}
    return {"ok": services["ollama"]["ok"], "services": services}


def dashboard_page() -> str:
    residency = run_json(["python3", "scripts/model_residency.py"])
    tokens = run_json(["scripts/control-tower", "tokens"])

    hot_rows = "".join(
        f"<tr><td class='hot'>{html.escape(m['model'])}</td><td>{m['vram_gb']} GB</td><td>{html.escape(m['expires_at'][:19])}</td></tr>"
        for m in residency.get("hot", [])
    ) or "<tr><td colspan='3'>No models currently resident (all cold -- next call will be a cold start)</td></tr>"

    events = []
    if EVENTS_LOG.exists():
        for line in EVENTS_LOG.read_text().splitlines()[-20:][::-1]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    event_rows = "".join(
        f"<tr><td>{datetime.fromtimestamp(e['timestamp'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}</td>"
        f"<td>{html.escape(e.get('agent_id',''))}</td><td>{html.escape(e.get('name',''))}</td>"
        f"<td class='{'fail' if e.get('status')=='failed' else ''}'>{html.escape(e.get('status',''))}</td>"
        f"<td>{e.get('latency_ms','')} ms</td></tr>"
        for e in events
    ) or "<tr><td colspan='5'>No real activity logged yet</td></tr>"

    return layout("Dashboard", f"""
    <p class="note">Every number below is read live -- model residency from Ollama's own API, token metrics and
    activity from control-tower's real event store (fed by job-portal's actual usage). Nothing here is cached or
    fabricated for display.</p>
    <div class="kpi-row">
      {kpi(residency.get('hot_count', '?'), 'Models hot (resident)')}
      {kpi(residency.get('total_installed', '?'), 'Models installed')}
      {kpi(tokens.get('calls', '?'), 'Real calls logged')}
      {kpi(tokens.get('output_tokens', '?'), 'Output tokens (all time)')}
    </div>

    <h3>Model residency right now</h3>
    <table><tr><th>Model</th><th>VRAM</th><th>Expires at</th></tr>{hot_rows}</table>

    <h3>Recent real activity (last 20)</h3>
    <table><tr><th>Time (UTC)</th><th>Agent</th><th>Model</th><th>Status</th><th>Latency</th></tr>{event_rows}</table>

    <h3>Benchmark</h3>
    <form method="post" action="/benchmark"><input type="hidden" name="csrf" value="{CSRF_TOKEN}">
      <button type="submit">Run real benchmark now (~70s, loads production models)</button></form>

    <h3>Execution gateway</h3>
    <p><a class="btn" href="/api/health">Live health</a> &nbsp;
       <a class="btn" href="/diagnostics">Diagnostics / drift</a> &nbsp;
       <a class="btn" href="/gpu">GPU lease/queue status</a> &nbsp;
       <a class="btn" href="/run">Prompt terminal</a> &nbsp;
       <a class="btn" href="/terminal">Operations terminal</a> &nbsp;
       <a class="btn" href="/capabilities">Capability map</a> &nbsp;
       <a class="btn" href="/security">Security layers (SAST/SBOM/DAST/runtime, in sequence)</a></p>
    """)


def gpu_page() -> str:
    status = run_json(["python3", "scripts/gpu_scheduler.py", "status"])
    queue_rows = "".join(
        f"<tr><td>{html.escape(e['job_id'])}</td><td>{e['priority']} ({html.escape(e['priority_name'])})</td>"
        f"<td>{datetime.fromtimestamp(e['arrival_ts'], tz=timezone.utc).strftime('%H:%M:%S')}</td></tr>"
        for e in status.get("queue", [])
    ) or "<tr><td colspan='3'>Queue empty</td></tr>"

    held = status.get("lease_held_by")
    held_html = f"<span class='hot'>{html.escape(held)}</span>" if held else "<span class='cold'>free</span>"

    return layout("GPU lease/queue", f"""
    <p class="note">Real-time snapshot of gpu_scheduler's Redis-backed priority queue and single-slot lease --
    this machine's Ollama runs with OLLAMA_NUM_PARALLEL=1, so exactly one inference request can hold the lease
    at a time.</p>
    <div class="kpi-row">
      {kpi(held_html, 'Lease held by')}
      {kpi(status.get('queue_depth', '?'), 'Queue depth')}
    </div>
    <h3>Queued jobs</h3>
    <table><tr><th>Job ID</th><th>Priority</th><th>Arrived (UTC)</th></tr>{queue_rows}</table>
    <p><a href="/">&larr; Back to dashboard</a></p>
    """)


def security_page() -> str:
    # Layer 1: SAST -- live re-run, same as the real CI gate
    semgrep = subprocess.run(
        ["semgrep", "--config", "p/python", "--config", "p/security-audit", "--json", "--quiet", "scripts/", "portal/"],
        capture_output=True, text=True, cwd=CONTROL_TOWER, timeout=120,
    )
    try:
        sast_findings = len(json.loads(semgrep.stdout).get("results", []))
    except Exception:
        sast_findings = None

    # Layer 2: SBOM/SCA -- generated fresh in CI on every push, not cached here
    # (syft/grype installs take real time; this page links to the real CI
    # artifact rather than re-running a multi-minute install on every page load)

    # Layer 3: DAST -- real ZAP baseline scan report, read from disk
    zap_summary = None
    if ZAP_REPORT.exists():
        try:
            zap_data = json.loads(ZAP_REPORT.read_text())
            alerts = zap_data.get("site", [{}])[0].get("alerts", [])
            zap_summary = {"count": len(alerts), "alerts": alerts, "generated": zap_data.get("@generated")}
        except Exception:
            zap_summary = None

    # Layer 4: Runtime -- real security-category events from the live log
    security_events = []
    if EVENTS_LOG.exists():
        for line in EVENTS_LOG.read_text().splitlines()[-300:][::-1]:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("category") == "security":
                security_events.append(e)
    security_events = security_events[:20]

    sast_html = (
        f"<div class='kpi'><div class='num'>{sast_findings}</div><div class='label'>Findings (live re-run)</div></div>"
        if sast_findings is not None else "<p class='fail'>semgrep run failed or not installed</p>"
    )

    if zap_summary:
        alert_rows = "".join(
            f"<tr><td>{html.escape(a.get('name',''))}</td><td>{html.escape(a.get('riskdesc',''))}</td></tr>"
            for a in zap_summary["alerts"]
        )
        dast_html = f"""
        <div class="kpi-row">
          {kpi(zap_summary['count'], 'Real findings')}
          {kpi(html.escape(str(zap_summary['generated'] or '')[:19]), 'Scan generated')}
        </div>
        <table><tr><th>Finding</th><th>Risk</th></tr>{alert_rows}</table>
        """
    else:
        dast_html = "<p class='note'>No ZAP report found -- run scripts described in docs/STRIDE_THREAT_MODEL.md.</p>"

    event_rows = "".join(
        f"<tr><td>{datetime.fromtimestamp(e['timestamp'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}</td>"
        f"<td>{html.escape(e.get('name',''))}</td><td class='{'fail' if e.get('status')=='blocked' else ''}'>{html.escape(e.get('status',''))}</td>"
        f"<td>{html.escape(str(e.get('reason', e.get('matched_patterns',''))))}</td></tr>"
        for e in security_events
    ) or "<tr><td colspan='4'>No security-category events logged yet</td></tr>"

    return layout("Security layers (in sequence)", f"""
    <p class="note">SAST and runtime events are live. SBOM/SCA are CI artifacts. DAST is shown only if this portal has its own scan report. See <code>docs/STRIDE_THREAT_MODEL.md</code>.</p>

    <h3>1. SAST -- static analysis (semgrep, live re-run)</h3>
    <div class="kpi-row">{sast_html}</div>

    <h3>2. SBOM / SCA -- dependency inventory + CVE scan</h3>
    <p>Generated fresh on every push in CI (syft + grype), not cached here.
    <a class="btn" href="https://github.com/PraveenAsthana123/ollama/actions" target="_blank">View latest run &rarr;</a></p>

    <h3>3. DAST -- dynamic scan (OWASP ZAP baseline, real report)</h3>
    {dast_html}

    <h3>4. Runtime -- rate limiter / injection guard / GPU lease (live event log)</h3>
    <table><tr><th>Time (UTC)</th><th>Control</th><th>Status</th><th>Detail</th></tr>{event_rows}</table>

    <p><a href="/">&larr; Back to dashboard</a></p>
    """)


def run_form(query: str = "", task_type: str = "text", route: str = "direct",
             result: dict | None = None, prepared_prompt: str = "") -> str:
    result_html = ""
    if result is not None:
        cache_badge = ""
        if result.get("cache_hit"):
            sim = f" (similarity {result['similarity']})" if "similarity" in result else ""
            cache_badge = f"<p class='note'>Served from {html.escape(result.get('cache_type','?'))} cache{sim} -- no real Ollama call this time.</p>"
        result_html = f"""
        <h3>Result</h3>
        {cache_badge}
        <table>
          <tr><th>Decision</th><td>{html.escape(str(result.get('decision')))}</td></tr>
          <tr><th>Model / tier</th><td>{html.escape(str(result.get('model','')))} / {html.escape(str(result.get('tier','')))}</td></tr>
          <tr><th>Cache hit</th><td>{result.get('cache_hit', False)}</td></tr>
          <tr><th>GPU wait</th><td>{result.get('gpu_wait_ms', '-')} ms</td></tr>
          <tr><th>Total latency</th><td>{result.get('latency_ms', '-')} ms</td></tr>
        </table>
        <h3>Response</h3>
        <pre style="white-space:pre-wrap;background:#fff;border:1px solid #e2e2e6;border-radius:8px;padding:1rem;">{html.escape(str(result.get('response', result.get('reason', ''))))}</pre>
        {f'<details><summary>Prompt sent to Ollama</summary><pre>{html.escape(prepared_prompt)}</pre></details>' if prepared_prompt else ''}
        """
    return layout("Prompt terminal", f"""
    <p class="note">Submits a tracked task through delegate.py and the real execution gateway -- Redis exact-cache check,
    Qdrant semantic-cache check, real GPU lease, real Ollama call on a miss. Claude preparation calls the Claude CLI first; direct mode stays local.</p>
    <form method="post" action="/run">
      <input type="hidden" name="csrf" value="{CSRF_TOKEN}">
      <p><textarea name="query" rows="5" maxlength="12000" style="width:100%;font-size:0.95rem;" placeholder="Describe the job, code, or text task...">{html.escape(query)}</textarea></p>
      <p>Task: <select name="task_type">
        <option value="text" {"selected" if task_type=="text" else ""}>Text</option>
        <option value="code" {"selected" if task_type=="code" else ""}>Code</option>
        <option value="job" {"selected" if task_type=="job" else ""}>Job</option>
      </select> Route: <select name="route">
        <option value="direct" {"selected" if route=="direct" else ""}>Direct Ollama</option>
        <option value="claude" {"selected" if route=="claude" else ""}>Claude prepares → Ollama executes</option>
      </select>
      <button type="submit">Run</button></p>
    </form>
    {result_html}
    <p><a href="/">&larr; Back to dashboard</a></p>
    """)


def terminal_page(command: str = "", output: str = "") -> str:
    return layout("Operations terminal", f"""
    <p class="note">Read-only Control Tower commands. No shell, arbitrary commands, file edits, or deployments.</p>
    <form method="post" action="/terminal">
      <input type="hidden" name="csrf" value="{CSRF_TOKEN}">
      <p><input name="command" value="{html.escape(command)}" style="width:80%;font-size:1rem" placeholder="help, status, residency, tokens, fleet, agentops, diagnose, delegations" maxlength="80">
      <button type="submit">Run</button></p>
    </form>
    <pre style="white-space:pre-wrap;background:#fff;padding:1rem">{html.escape(output)}</pre>
    <p><a href="/run">Prompt terminal</a> · <a href="/">Dashboard</a></p>
    """)


def diagnostics_page() -> str:
    state = run_json(["python3", "scripts/diagnose_stack.py"])
    fleet = run_json(["scripts/control-tower", "fleet"])
    agentops = run_json(["scripts/control-tower", "agentops", "gate"])
    tokens = run_json(["scripts/control-tower", "tokens"])
    rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{html.escape(status)}</td></tr>"
                   for name, status in state.get("units", {}).items())
    problems = "".join(f"<li>{html.escape(problem)}</li>" for problem in state.get("problems", []))
    return layout("Diagnostics and drift", f"""
    <p class="note">Live read-only checks. Events are the most recent 200; this is an operations view, not a quality evaluation.</p>
    <div class="kpi-row">
      {kpi(state.get('installed_models', '?'), 'Installed models')}
      {kpi(len(state.get('resident_models', [])), 'Resident models')}
      {kpi(state.get('recent_events', '?'), 'Recent events')}
      {kpi(fleet.get('totals', {}).get('agents', '?'), 'Active agents')}
      {kpi(tokens.get('input_tokens', '?'), 'Measured input tokens')}
    </div>
    <h3>Services</h3><table><tr><th>Unit</th><th>State</th></tr>{rows}</table>
    <h3>Problems</h3><ul>{problems or '<li>No problem detected by these checks</li>'}</ul>
    <h3>AgentOps quality gate</h3>
    <p>{'PASS' if agentops.get('passed') else 'FAIL'} — {html.escape(', '.join(agentops.get('failures', [])) or 'No failing gates')}</p>
    <p>Recorded sessions: {agentops.get('sessions', '?')}; measured cache hits: {tokens.get('cached_tokens', '?')} tokens.</p>
    <h3>Known implementation gaps</h3>
    <ul><li>Claude delegation from the CLI is instructed, not enforced by a hook.</li>
    <li>Agent supervision, creation, and self-healing modules need task-specific live evaluations.</li>
    <li>Prompt compression and KV-cache adapters remain disabled pending benchmarks.</li>
    <li>Semantic-cache quality needs recurring tests with isolated state.</li></ul>
    <p><a href="/terminal">Operations terminal</a> · <a href="/">Dashboard</a></p>
    """)


def capabilities_page() -> str:
    features = [
        ("Prompt routing", "Live", "Portal direct and Claude-prepared requests execute through delegate.py"),
        ("Task reporting", "Live", "Delegation records in operations terminal: delegations"),
        ("Agent supervisor / harness", "Implemented", "Supervisor and harness CLIs; no active fleet agents in latest audit"),
        ("Exact / semantic cache", "Live", "Redis and Qdrant; identity-sensitive matches are rejected"),
        ("Token limits", "Live", "Ollama num_ctx and num_predict; native input accounting remains open"),
        ("MCP gateway / mesh", "Shared runtime", "SohamYoga ContextForge container is healthy on host; no Control Tower integration verified"),
        ("Tracing / evaluation", "Partial", "Local events exist; AgentOps quality gate currently fails"),
        ("SAST", "Live/CI", "Semgrep locally and in GitHub Actions"),
        ("SBOM / SCA", "CI", "Syft CycloneDX artifact and Grype scan"),
        ("DAST / API security", "Gap", "No current portal-specific ZAP baseline report"),
        ("CBOM", "Gap", "Cryptographic inventory not generated"),
        ("SIEM / EDR / XDR / SOAR", "Gap", "No Wazuh or equivalent deployment verified"),
    ]
    rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{html.escape(status)}</td><td>{html.escape(evidence)}</td></tr>"
                   for name, status, evidence in features)
    return layout("Capability map", f"""
    <p class="note">Status is scoped to this Ollama project. Implemented code is distinguished from a running production integration.</p>
    <table><tr><th>Function</th><th>Status</th><th>Evidence / gap</th></tr>{rows}</table>
    <p>See <code>docs/OPERATIONS_GAP_CHECKLIST.md</code> and <code>docs/GITHUB_FEATURE_REVIEW.md</code> for the audit and candidate projects.</p>
    <p><a href="/diagnostics">Live diagnostics</a> · <a href="/">Dashboard</a></p>
    """)


def benchmark_page() -> str:
    result = subprocess.run(
        [CONTROL_TOWER_PYTHON, "scripts/bench_production_models.py"],
        capture_output=True, text=True, cwd=CONTROL_TOWER, timeout=200,
    )
    out = result.stdout
    # pull the JSON summary block from the tail of stdout
    try:
        summary = json.loads(out.split("=== Summary ===")[1].strip())
    except Exception:
        summary = None

    if summary:
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{html.escape(json.dumps(v))}</td></tr>"
            for k, v in summary.items()
        )
        body = f"<table><tr><th>Run</th><th>Result</th></tr>{rows}</table>"
    else:
        body = f"<pre>{html.escape(out)}</pre><pre class='fail'>{html.escape(result.stderr)}</pre>"

    return layout("Benchmark (just ran, real)", f"""
    <p class="note">This just ran for real against the live Ollama instance -- cold-unloads the model first, so the
    first row's timing reflects a genuine cold start, not a cached number.</p>
    {body}
    <p><a href="/">&larr; Back to dashboard</a></p>
    """)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            health = health_status()
            payload = json.dumps(health).encode("utf-8")
            self.send_response(200 if health["ok"] else 503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        try:
            if path == "/" or path == "/dashboard":
                page = dashboard_page()
            elif path == "/benchmark":
                page = layout("Benchmark", "<p>Run the benchmark from the dashboard to confirm this expensive model test.</p>")
            elif path == "/gpu":
                page = gpu_page()
            elif path == "/run":
                page = run_form()
            elif path == "/terminal":
                page = terminal_page()
            elif path == "/diagnostics":
                page = diagnostics_page()
            elif path == "/capabilities":
                page = capabilities_page()
            elif path == "/security":
                page = security_page()
            else:
                self.send_response(404)
                self.end_headers()
                return
        except Exception as exc:
            page = layout("Error", f"<p class='fail'>{html.escape(str(exc))}</p>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/run", "/terminal", "/benchmark"}:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 16000:
            self.send_error(413, "Request too large")
            return
        fields = parse_qs(self.rfile.read(length).decode("utf-8"))
        if not hmac.compare_digest(fields.get("csrf", [""])[0], CSRF_TOKEN):
            self.send_error(403, "Invalid form token")
            return
        if path == "/benchmark":
            page = benchmark_page()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return
        if path == "/terminal":
            command = fields.get("command", [""])[0].strip()
            try:
                page = terminal_page(command, terminal_command(command))
            except Exception as exc:
                page = terminal_page(command, f"Error: {type(exc).__name__}")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return
        query = (fields.get("query", [""])[0]).strip()
        task_type = fields.get("task_type", ["text"])[0]
        route = fields.get("route", ["direct"])[0]
        try:
            prompt, kind = prepare_task(query, task_type, route)
            result = run_json(["python3", "scripts/delegate.py", "run", f"Portal {task_type} request",
                               prompt, "--kind", kind])
            page = run_form(query, task_type, route, result, prompt)
        except Exception as exc:
            page = run_form(query, task_type, route, {"decision": "error", "reason": str(exc)})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8795)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Ollama Portal on http://127.0.0.1:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Incident responder

A small service that receives Grafana alerts, collects a bounded evidence packet
from the observability stack, and starts a headless coding agent to investigate.

```
Grafana alert ──webhook──▶ POST /alerts :8001 ──▶ incidents/<ts>-<name>/
                                                     alert.json
                                                     evidence.json   (Prometheus + Loki + Tempo)
                                                     agent-response.txt
```

## Run it

The responder runs on the **host**, not in a container, so it can reuse the
host's coding-agent login and the checked-out repository. Grafana (in Docker)
reaches it at `host.docker.internal:8001`.

```bash
python3 incident-response/responder.py
```

Configuration (environment variables):

| Variable | Default | Purpose |
| --- | --- | --- |
| `RESPONDER_PORT` | `8001` | listen port |
| `RESPONDER_AGENT_CMD` | `pi -p --approve --no-session {prompt}` | the agent command; `{prompt}` must be its own token |
| `RESPONDER_REPO` | repo root | working root for the agent |
| `PROMETHEUS_URL` / `LOKI_URL` / `TEMPO_URL` | `localhost` | where to collect evidence |
| `RESPONDER_LOOKBACK_SECONDS` | `900` | evidence window |

The agent is configuration, not code — switch vendors by changing one variable:

```bash
RESPONDER_AGENT_CMD='codex exec --dangerously-bypass-approvals-and-sandbox {prompt}' \
  python3 incident-response/responder.py
```

## Test it

```bash
curl -X POST http://localhost:8001/alerts \
  -H 'Content-Type: application/json' \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"ResponderTest","test":"true"},"annotations":{"summary":"Test notification; no incident to fix"}}]}'
```

It returns `202` immediately and runs the agent in the background. Read the
result from `incident-response/incidents/<timestamp>-ResponderTest/`:
`agent-response.txt` is the answer, `agent-status.json` records the exit code,
the commit before/after and whether the working tree changed, and
`evidence.json` is what the agent was given.

## What this deliberately does not do

This is the proof of concept the homework asks for, and the module's own text is
the honest description of its limits. Production would add:

- **Autonomy limits** — the agent runs with full tool access here. A real setup
  grades actions (read-only first, write behind approval) and never hands a
  model general production credentials. The module's principle applies: the
  model may reason, the system must observe, authorize, verify and remember.
- **Recovery verification** — this responder records the agent's commit but does
  not itself confirm the service recovered. `runbooks/verify-recovery.sh` is the
  missing step: replay the request and check the status.
- **Isolation** — the agent should run in a container job with an allowlist and
  scoped credentials, not directly on the host.
- **Escalation** — no path to a human when the agent cannot fix the problem.

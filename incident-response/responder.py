#!/usr/bin/env python3
"""On-call incident responder.

Question 5 of Homework 4: receive Grafana alerts on POST /alerts (port 8001),
save the evidence needed to understand the problem (endpoint, logs, traces),
then start a headless coding agent to investigate.

Design notes
------------
* Evidence first, model second. The agent reasons over collected facts; it does
  not go fishing through production. The packet is on disk even if the agent fails.
* The agent command is configuration, not code (`RESPONDER_AGENT_CMD`), so the
  responder does not depend on one vendor's CLI.
* The webhook returns 202 immediately: Grafana has a delivery timeout and the
  agent takes minutes. The run continues in a background thread.

This is a proof of concept and runs on the host so it can reuse the host's agent
login and working copy. Production would run the agent as a container job with an
allowlist, scoped credentials and a recovery-verification step -- see README.md.
"""
import json
import os
import shlex
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.getenv("RESPONDER_REPO", HERE.parent))
INCIDENTS = Path(os.getenv("RESPONDER_INCIDENTS", HERE / "incidents"))
PORT = int(os.getenv("RESPONDER_PORT", "8001"))

# Vendor-neutral: `{prompt}` must be its own token. Swap for
# "codex exec --dangerously-bypass-approvals-and-sandbox {prompt}" etc.
AGENT_CMD = os.getenv("RESPONDER_AGENT_CMD", "pi -p --approve --no-session {prompt}")

PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
LOKI = os.getenv("LOKI_URL", "http://localhost:3100")
TEMPO = os.getenv("TEMPO_URL", "http://localhost:3200")
LOOKBACK_SECONDS = int(os.getenv("RESPONDER_LOOKBACK_SECONDS", "900"))


def http_json(url, params=None, timeout=20):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode())


def collect_evidence():
    """Bounded, read-only lookback across the three telemetry stores."""
    now = time.time()
    start = now - LOOKBACK_SECONDS
    evidence = {}

    def safe(name, fn):
        try:
            evidence[name] = fn()
        except Exception as exc:  # one missing signal must not stop the investigation
            evidence[name] = {"error": f"{type(exc).__name__}: {exc}"}

    safe(
        "metrics",
        lambda: http_json(
            f"{PROMETHEUS}/api/v1/query",
            {"query": "sum by (http_target, http_status_code) "
                      "(increase(http_server_duration_milliseconds_count[15m]))"},
        ),
    )
    safe(
        "errors",
        lambda: http_json(
            f"{PROMETHEUS}/api/v1/query",
            {"query": 'sum by (http_target, http_status_code) '
                      '(increase(http_server_duration_milliseconds_count'
                      '{http_status_code=~"5.."}[15m]))'},
        ),
    )
    safe(
        "logs",
        lambda: http_json(
            f"{LOKI}/loki/api/v1/query_range",
            {"query": '{service_name="order-tracker"}', "limit": "200",
             "start": str(int(start * 1e9)), "end": str(int(now * 1e9))},
        ),
    )

    def traces():
        search = http_json(
            f"{TEMPO}/api/search",
            {"limit": "50", "start": str(int(start)), "end": str(int(now))},
        )
        details = []
        for trace in search.get("traces", [])[:20]:
            try:
                details.append(http_json(f"{TEMPO}/api/traces/{trace['traceID']}"))
            except Exception:
                pass
        return {"search": search, "details": details}

    safe("traces", traces)
    return evidence


def git(*args):
    try:
        return subprocess.run(("git", *args), cwd=str(REPO), capture_output=True,
                              text=True, timeout=30).stdout
    except Exception as exc:
        return f"<git {args} failed: {exc}>\n"


def agent_command(prompt):
    return [prompt if part == "{prompt}" else part for part in shlex.split(AGENT_CMD)]


def run_agent(incident_dir, prompt):
    command = agent_command(prompt)
    (incident_dir / "agent-command.txt").write_text(shlex.join(command) + "\n")
    started = datetime.now(timezone.utc).isoformat()
    before = git("rev-parse", "HEAD")

    # The outcome is recorded even if the agent cannot be launched. A responder that
    # dies silently cannot be audited, and the module's point is that the system must
    # remember what it did.
    exit_code = -1
    error = None
    with open(incident_dir / "agent-response.txt", "w") as out:
        try:
            result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT,
                                    cwd=str(REPO), stdin=subprocess.DEVNULL)
            exit_code = result.returncode
        except Exception as exc:  # noqa: BLE001 - deliberately broad, must be recorded
            error = f"{type(exc).__name__}: {exc}"
            out.write(f"agent failed to run: {error}\n")

    answer = (incident_dir / "agent-response.txt").read_text().strip()
    (incident_dir / "agent-status.json").write_text(json.dumps({
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": exit_code,
        "error": error,
        "commit_before": before.strip(),
        "commit_after": git("rev-parse", "HEAD").strip(),
        "git_status": git("status", "--porcelain"),
        "answer_last_line": answer.splitlines()[-1] if answer else "",
    }, indent=2) + "\n")
    print(f"[responder] agent finished for {incident_dir.name} (exit {exit_code})", flush=True)


def handle_alert(alert):
    alertname = (alert.get("labels") or {}).get("alertname", "unknown")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    incident_dir = INCIDENTS / f"{stamp}-{alertname}"
    incident_dir.mkdir(parents=True, exist_ok=True)

    (incident_dir / "alert.json").write_text(json.dumps(alert, indent=2) + "\n")
    (incident_dir / "evidence.json").write_text(json.dumps(collect_evidence(), indent=2) + "\n")

    template = (HERE / "responder-task.md").read_text()
    prompt = template.replace("{{REPO}}", str(REPO)).replace("{{INCIDENT_DIR}}", str(incident_dir))
    (incident_dir / "prompt.md").write_text(prompt + "\n")

    print(f"[responder] incident {incident_dir.name} created; starting agent", flush=True)
    # ponytail: no de-duplication. Grafana re-sends a firing alert every
    # repeat_interval, so an ongoing incident can start several agents on the same
    # problem (observed in Q6: two runs, the second raced the first). Add an
    # in-flight set keyed by alertname + route when repeat notifications matter.
    threading.Thread(target=run_agent, args=(incident_dir, prompt), daemon=True).start()
    return incident_dir


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alerts":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "invalid JSON")
            return

        alerts = payload.get("alerts") if isinstance(payload, dict) else None
        if alerts is None:
            alerts = [payload] if payload else []
        firing = [a for a in alerts if a.get("status", "firing") == "firing"]

        incidents = [str(handle_alert(a)) for a in firing]
        response = json.dumps({"accepted": len(incidents), "incidents": incidents}).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, fmt, *args):
        print(f"[responder] {fmt % args}", flush=True)


if __name__ == "__main__":
    INCIDENTS.mkdir(parents=True, exist_ok=True)
    print(f"[responder] listening on 0.0.0.0:{PORT}", flush=True)
    print(f"[responder] repo={REPO}", flush=True)
    print(f"[responder] agent={AGENT_CMD}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

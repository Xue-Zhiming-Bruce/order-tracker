# On-call task

You are the on-call engineer for the Order Tracker repository at `/Users/xuezhiming/Desktop/Learnings/DataTalksClub/AI Dev Tools Zoomcamp/Homework4`.

A Grafana alert just fired. The alert and the evidence collected from the
observability stack are in this incident directory:

```
/Users/xuezhiming/Desktop/Learnings/DataTalksClub/AI Dev Tools Zoomcamp/Homework4/incident-response/incidents/20260929-110431-ResponderTest
  alert.json      the alert that fired (endpoint, time window, dashboard link)
  evidence.json   read-only lookback from Prometheus, Loki and Tempo
  prompt.md       this task
```

`evidence.json` contains three keys: `metrics` and `errors` (Prometheus),
`logs` (Loki) and `traces` (Tempo, both the search result and the full traces).
The application code is `app/main.py`. Tests run with `uv run --frozen pytest -q`.
The app is running at `http://localhost:8000`.

Do this:

1. Read `alert.json` and `evidence.json`. Identify the affected route, the
   failing HTTP status code and the timeframe. If the evidence is empty, say so
   rather than inventing facts.
2. Read the code and **reproduce the failure** against the running app with
   `curl`. Use the evidence to pick which request to replay.
3. If you find a real bug: make the smallest correction, run the backend tests,
   and `git commit` the fix with a clear message. Do not change tests to make a
   failure disappear, and do not "fix" anything unrelated to the alert.
4. If the alert is a false positive — for example a test notification with no
   incident to fix — explain why and **change nothing**.

Finish with a short report: root cause, the fix (or why none is needed), the
exact command you used to reproduce, and how you verified the result.


#!/usr/bin/env bash
# Recovery verification: replay the request that caused the incident and check it
# no longer returns a server error. The agent's commit is not accepted as proof.
set -euo pipefail

BASE_URL="${ORDER_TRACKER_URL:-http://localhost:8000}"
ORDER_ID="${ORDER_ID:-express-1002}"

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/api/orders/$ORDER_ID")
echo "GET /api/orders/$ORDER_ID -> HTTP $code"

if [ "$code" -ge 500 ]; then
  echo "RECOVERY FAILED: still a server error"
  exit 1
fi

echo "RECOVERY OK"

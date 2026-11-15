#!/usr/bin/env bash
# Send the post-event summary email to everyone with a bracelet at the test
# event (the server from local-server.sh must be running).
#   ./scripts/send-summaries.sh            send to anyone not emailed yet
#   ./scripts/send-summaries.sh --resend   send again to everyone
set -euo pipefail
BACKEND="$(cd "$(dirname "$0")/../backend" && pwd)"
set -a; . "$BACKEND/.env"; set +a

EVENT_ID="${EVENT_ID:-$(curl -sf http://127.0.0.1:8000/events | "$BACKEND/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')}"
RESEND=false; [ "${1:-}" = "--resend" ] && RESEND=true

curl -sS -X POST "http://127.0.0.1:8000/events/$EVENT_ID/send-summaries" \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d "{\"resend\": $RESEND}"
echo

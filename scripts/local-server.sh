#!/usr/bin/env bash
# Run trO on this computer so a phone on the same Wi-Fi can test the real flow:
# sign up, set preferences, link a bracelet, and get the summary email.
#
#   ./scripts/local-server.sh            start everything (Ctrl-C stops it)
#   ./scripts/send-summaries.sh          send the summary emails for the test event
#
# First run creates backend/.env with fresh secrets. Emails are saved as files
# in backend/media/outbox until you put Gmail details in backend/.env (see the
# SMTP_* lines there) and set EMAIL_BACKEND=smtp.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
EVENT_NAME="${EVENT_NAME:-trO test event}"

# --- This computer's address on the Wi-Fi ----------------------------------
lan_ip() {
  ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{print $1}' || true
}
# APP_HOST overrides it, e.g. the IPv6 address on a phone hotspot.
IP="${APP_HOST:-$(lan_ip)}"
IP="${IP:-localhost}"
case "$IP" in *:*) IP="[$IP]" ;; esac  # IPv6 needs brackets in a URL
APP_URL="http://$IP:5173"

# --- Backend setup ----------------------------------------------------------
cd "$BACKEND"
if [ ! -d .venv ]; then
  echo "Setting up Python environment (first run only)..."
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  echo "Creating backend/.env with new secrets..."
  secret() { .venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"; }
  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$(secret)|" \
      -e "s|^ADMIN_API_KEY=.*|ADMIN_API_KEY=$(secret)|" \
      -e "s|^BRACELET_API_KEY=.*|BRACELET_API_KEY=$(secret)|" \
      .env.example > .env
fi
# The phone opens the app at this computer's address; keep it current.
# LinkedIn sends the phone back through the web app's /api proxy, so the
# callback lives at this address too (add it to the LinkedIn app's redirect URLs).
LINKEDIN_CALLBACK="$APP_URL/api/auth/linkedin/callback"
sed -i.bak -e "s|^FRONTEND_URL=.*|FRONTEND_URL=$APP_URL|" -e "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$APP_URL|" \
    -e "s|^LINKEDIN_REDIRECT_URI=.*|LINKEDIN_REDIRECT_URI=$LINKEDIN_CALLBACK|" .env && rm -f .env.bak

set -a; . ./.env; set +a

# --- Frontend setup ---------------------------------------------------------
cd "$FRONTEND"
[ -d node_modules ] || { echo "Installing web app packages (first run only)..."; npm ci --silent; }

# --- Start both servers -----------------------------------------------------
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

cd "$BACKEND"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
PIDS+=($!)

cd "$FRONTEND"
VITE_API_URL=/api npx vite --host --port 5173 --strictPort --clearScreen false --logLevel warn &
PIDS+=($!)

# Wait for the API, then make sure the test event exists.
for _ in $(seq 1 40); do curl -sf http://127.0.0.1:8000/events >/dev/null && break; sleep 0.5; done
EVENT_ID="$(curl -sf http://127.0.0.1:8000/events | .venv/bin/python -c 'import json,sys; e=json.load(sys.stdin); print(e[0]["id"] if e else "")' 2>/dev/null || true)"
if [ -z "$EVENT_ID" ]; then
  EVENT_ID="$(curl -sf -X POST http://127.0.0.1:8000/events \
    -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
    -d "{\"name\": \"$EVENT_NAME\"}" | "$BACKEND/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi

cat <<EOF

  trO is running on this computer.

  On your phone (same Wi-Fi), open:
    $APP_URL/e/$EVENT_ID?b=TEST01

  Each test person needs their own bracelet code: change TEST01 to TEST02, ...
  Email delivery: EMAIL_BACKEND=$EMAIL_BACKEND$( [ "$EMAIL_BACKEND" = console ] && echo " (saved to backend/media/outbox, not sent)")
  Send the summary emails:  ./scripts/send-summaries.sh
  LinkedIn sign-in: $( [ -n "${LINKEDIN_CLIENT_ID:-}" ] && echo "on" || echo "off (run ./scripts/setup-linkedin.sh)")
    Redirect URL to add in the LinkedIn app: $LINKEDIN_CALLBACK

  Ctrl-C to stop.
EOF

wait

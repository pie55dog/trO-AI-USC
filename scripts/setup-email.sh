#!/usr/bin/env bash
# Make trO send its emails from an account you own. Run it in Terminal:
#   ./scripts/setup-email.sh
# It asks for the address and an app password (typed here, never sent anywhere
# but your mail provider), tests the login, and saves it to backend/.env.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" "$ROOT/scripts/setup_email.py"

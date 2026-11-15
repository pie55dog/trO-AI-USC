#!/usr/bin/env bash
# Turn on LinkedIn sign-in (backend /auth/linkedin). Run it in Terminal:
#   ./scripts/setup-linkedin.sh
# It asks for your LinkedIn app's Client ID and Client Secret and saves them
# to backend/.env (the secret is typed here, never sent anywhere).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" "$ROOT/scripts/setup_linkedin.py"

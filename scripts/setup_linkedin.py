#!/usr/bin/env python3
"""Turn on LinkedIn sign-in (backend /auth/linkedin) (run via scripts/setup-linkedin.sh).

Asks for your LinkedIn app's Client ID and Client Secret in the terminal (the
secret is hidden and never leaves this computer) and saves them to
backend/.env. Get them from https://www.linkedin.com/developers/apps:
create an app, add the product "Sign In with LinkedIn using OpenID Connect",
then open the Auth tab.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_email import ENV_FILE, check_safe, update_env  # noqa: E402


def main() -> int:
    if not ENV_FILE.exists():
        print("backend/.env doesn't exist yet. Run ./scripts/local-server.sh once first.")
        return 1

    client_id = input("LinkedIn Client ID: ").strip()
    print("Paste the Client Secret (nothing shows as you type).")
    client_secret = getpass.getpass("Client Secret: ").strip()
    try:
        check_safe("The Client ID", client_id)
        check_safe("The Client Secret", client_secret)
    except ValueError as exc:
        print(exc)
        return 1

    update_env(ENV_FILE, {"LINKEDIN_CLIENT_ID": client_id, "LINKEDIN_CLIENT_SECRET": client_secret})
    print("\nSaved to backend/.env.")
    print("Restart the server (Ctrl-C, then ./scripts/local-server.sh). It prints the")
    print("redirect URL to add under Auth > Authorized redirect URLs in the LinkedIn app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Point trO's emails at an account you own (run via scripts/setup-email.sh).

Asks for the account's address and its app password in the terminal (the
password is hidden and never leaves this computer), checks they work by
logging in to the mail server, saves them to backend/.env, and sends one
confirmation email to the account itself.

An app password is a separate password for apps, not your normal one. For
Gmail: Google Account > Security > 2-Step Verification > App passwords.
"""

from __future__ import annotations

import getpass
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"

# Mail servers for common providers: domain -> (host, port).
PROVIDERS = {
    "gmail.com": ("smtp.gmail.com", 587),
    "googlemail.com": ("smtp.gmail.com", 587),
    "outlook.com": ("smtp-mail.outlook.com", 587),
    "hotmail.com": ("smtp-mail.outlook.com", 587),
    "live.com": ("smtp-mail.outlook.com", 587),
    "icloud.com": ("smtp.mail.me.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587),
}

# The .env file is read by the shell, so keep out characters it would act on.
UNSAFE = set('"$`\\\n\r')


def check_safe(name: str, value: str) -> str:
    if not value or UNSAFE & set(value):
        raise ValueError(f"{name} is empty or has a character that can't be saved (\" $ ` \\).")
    return value


def update_env(path: Path, values: dict[str, str]) -> None:
    """Set KEY=value lines in ``path``, keeping every other line as it is."""
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if not line.lstrip().startswith("#") and key in remaining:
            lines[i] = f'{key}="{remaining.pop(key)}"'
    lines += [f'{k}="{v}"' for k, v in remaining.items()]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)  # holds secrets: only you can read it


def smtp_session(host: str, port: int, user: str, password: str) -> smtplib.SMTP:
    server = smtplib.SMTP(host, port, timeout=20)
    server.starttls(context=ssl.create_default_context())
    server.login(user, password)
    return server


def main() -> int:
    if not ENV_FILE.exists():
        print("backend/.env doesn't exist yet. Run ./scripts/local-server.sh once first.")
        return 1

    address = input("Email address trO should send from: ").strip()
    if "@" not in address:
        print("That doesn't look like an email address.")
        return 1
    domain = address.rsplit("@", 1)[1].lower()
    host, port = PROVIDERS.get(domain, (None, 587))
    if host is None:
        host = input(f"Outgoing mail (SMTP) server for {domain}, e.g. smtp.{domain}: ").strip()
    print("Paste the app password (nothing shows as you type; spaces are fine).")
    password = getpass.getpass("App password: ").replace(" ", "")

    try:
        check_safe("The address", address)
        check_safe("The server", host)
        check_safe("The password", password)
    except ValueError as exc:
        print(exc)
        return 1

    print(f"Checking the login with {host} ...")
    try:
        server = smtp_session(host, port, address, password)
    except smtplib.SMTPAuthenticationError:
        print(
            "The server refused that login. Use an app password, not your normal password\n"
            "(Gmail: Google Account > Security > 2-Step Verification > App passwords)."
        )
        return 1
    except (OSError, smtplib.SMTPException) as exc:
        print(f"Couldn't reach {host}:{port}: {exc}")
        return 1

    update_env(
        ENV_FILE,
        {
            "EMAIL_BACKEND": "smtp",
            "EMAIL_FROM": f"trO <{address}>",
            "SMTP_HOST": host,
            "SMTP_PORT": str(port),
            "SMTP_USERNAME": address,
            "SMTP_PASSWORD": password,
            "SMTP_STARTTLS": "true",
        },
    )

    message = EmailMessage()
    message["From"], message["To"] = f"trO <{address}>", address
    message["Subject"] = "trO emails are set up"
    message.set_content("trO will now send its emails from this account.")
    try:
        server.send_message(message)
    finally:
        server.quit()

    print(f"\nSaved to backend/.env. A confirmation email is on its way to {address}.")
    print("Restart the server (Ctrl-C, then ./scripts/local-server.sh) for trO to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Sending email, and the post-event "who you met" email.

Two backends, picked with EMAIL_BACKEND:

* ``smtp``: really sends, using Python's standard library (no third-party
  service). Works with any SMTP account, e.g. a Gmail account with an app
  password (smtp.gmail.com:587) or a USC Office 365 mailbox.
* ``apps_script``: posts the email over https to a small Google Apps Script
  web app (deploy/email-relay.gs) that sends it from your Gmail. For hosts
  that block SMTP ports, like Render's free tier.
* ``console``: writes each email to MEDIA_DIR/outbox/ as a .eml file you can
  open in any mail app. For local development and tests only.

The post-event email lists everyone the attendee connected with and the
contact info each person chose to share. AI conversation summaries and
follow-up suggestions are NOT generated yet; the template has a clearly
marked slot for them (see ``ConnectionEntry.summary``).
"""

from __future__ import annotations

import html
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Optional, Protocol

import httpx

from .config import Settings


class EmailError(Exception):
    """Sending failed (bad credentials, server down, rejected address...)."""


class EmailBackend(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ConsoleBackend:
    """Saves emails as .eml files instead of sending them."""

    def __init__(self, outbox: Path):
        self.outbox = outbox

    def send(self, message: EmailMessage) -> None:
        self.outbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        # Message-ID is unique, so two emails in the same microsecond don't collide.
        msg_id = "".join(c for c in message["Message-ID"] if c.isalnum())[:24]
        (self.outbox / f"{stamp}-{msg_id}.eml").write_bytes(bytes(message))


class SMTPBackend:
    """Sends through an SMTP server."""

    def __init__(self, settings: Settings):
        if not settings.smtp_host:
            raise EmailError("SMTP_HOST is not set")
        self.settings = settings

    def send(self, message: EmailMessage) -> None:
        s = self.settings
        context = ssl.create_default_context()
        try:
            if s.smtp_port == 465:
                # Port 465 is TLS from the first byte.
                server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=context, timeout=30)
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
            with server:
                if s.smtp_port != 465 and s.smtp_starttls:
                    server.starttls(context=context)
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"{type(exc).__name__}: {exc}") from exc


class AppsScriptBackend:
    """Sends through the Google Apps Script relay in deploy/email-relay.gs."""

    def __init__(self, settings: Settings):
        if not (settings.email_relay_url and settings.email_relay_key):
            raise EmailError("EMAIL_RELAY_URL and EMAIL_RELAY_KEY must be set")
        self.settings = settings

    def send(self, message: EmailMessage) -> None:
        text_part = message.get_body(preferencelist=("plain",))
        html_part = message.get_body(preferencelist=("html",))
        sender_name = message["From"].addresses[0].display_name if message["From"] else ""
        body = {
            "key": self.settings.email_relay_key,
            "to": str(message["To"]),
            "subject": str(message["Subject"]),
            "text": text_part.get_content() if text_part else "",
            "html": html_part.get_content() if html_part else "",
            "name": sender_name or "Tro",
        }
        try:
            # Apps Script answers a POST with a redirect to the result.
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                resp = client.post(self.settings.email_relay_url, json=body)
            result = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmailError(f"email relay unreachable: {type(exc).__name__}: {exc}") from exc
        if not result.get("ok"):
            raise EmailError(f"email relay refused: {result.get('error', 'unknown error')}")


def get_backend(settings: Settings) -> EmailBackend:
    """Pick the backend named by EMAIL_BACKEND."""
    if settings.email_backend == "smtp":
        return SMTPBackend(settings)
    if settings.email_backend == "apps_script":
        return AppsScriptBackend(settings)
    if settings.email_backend == "console":
        return ConsoleBackend(settings.media_dir / "outbox")
    raise EmailError(f"unknown EMAIL_BACKEND {settings.email_backend!r} (use 'smtp', 'apps_script' or 'console')")


def build_message(settings: Settings, to: str, subject: str, text: str, html_body: str) -> EmailMessage:
    """A multipart email with a plain-text and an HTML version.

    Mail apps show the HTML; the text part is for clients that can't, and it
    also helps keep the email out of spam folders.
    """
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="tro")
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    return msg


# --- Post-event email --------------------------------------------------------


@dataclass
class ConnectionEntry:
    """One person the recipient met, as shown in the email."""

    name: str
    # (label, value) pairs the person chose to share, e.g. ("Email", "x@usc.edu").
    contact: list[tuple[str, str]] = field(default_factory=list)
    headline: Optional[str] = None  # e.g. "Computer Science · USC"
    # Starred with the bracelet button: "follow up with this one".
    starred: bool = False
    # AI summary of the recorded conversation (only if both consented).
    summary: Optional[str] = None
    # Promises either person made, checked against the transcript.
    promises: list[str] = field(default_factory=list)
    # The recipient's own voice notes about this person.
    notes: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _contact_html(label: str, value: str) -> str:
    """Render one contact item; links only for safe http(s) and email values."""
    if label == "Email":
        return f'{_esc(label)}: <a href="mailto:{_esc(value)}">{_esc(value)}</a>'
    if value.lower().startswith(("http://", "https://")):
        return f'{_esc(label)}: <a href="{_esc(value)}">{_esc(value)}</a>'
    return f"{_esc(label)}: {_esc(value)}"


def render_post_event_email(
    recipient_name: str, event_name: str, connections: list[ConnectionEntry], other_notes: Optional[list[str]] = None
) -> tuple[str, str, str]:
    """Return (subject, text, html) for one attendee's post-event email.

    All user-provided text is HTML-escaped: profile fields come from other
    attendees, so they must never be able to inject markup into someone
    else's inbox.
    """
    first_name = recipient_name.split()[0] if recipient_name.strip() else "there"
    count = len(connections)
    people = "person" if count == 1 else "people"
    subject = f"Your connections from {event_name}"

    # Plain-text version.
    lines = [f"Hi {first_name},", ""]
    if count:
        lines.append(f"You met {count} {people} at {event_name}. Here's who:")
    else:
        lines.append(f"Thanks for coming to {event_name}! We didn't record any taps for you this time.")
    for c in connections:
        lines += ["", f"- {'★ ' if c.starred else ''}{c.name}" + (f" ({c.headline})" if c.headline else "")]
        lines += [f"    {label}: {value}" for label, value in c.contact]
        if c.summary:
            lines.append(f"    What you talked about: {c.summary}")
        lines += [f"    Promised: {p}" for p in c.promises]
        lines += [f"    Your note: {n}" for n in c.notes]
        lines += [f"    Follow up: {f}" for f in c.follow_ups]
    other_notes = other_notes or []
    if other_notes:
        lines += ["", "Your other notes:"] + [f"- {n}" for n in other_notes]
    if any(c.summary for c in connections):
        lines += ["", "The recordings and transcripts behind these notes are now deleted."]
    lines += ["", "See you at the next one,", "Tro"]
    text = "\n".join(lines)

    # HTML version: simple inline styles, since many mail apps strip <style>.
    cards = []
    for c in connections:
        star = '<span style="color:#FFCC00">★</span> ' if c.starred else ""
        parts = [f'<p style="margin:0;font-size:18px;font-weight:600">{star}{_esc(c.name)}</p>']
        if c.headline:
            parts.append(f'<p style="margin:4px 0 0;color:#555">{_esc(c.headline)}</p>')
        if c.contact:
            items = "".join(f'<li style="margin:2px 0">{_contact_html(l, v)}</li>' for l, v in c.contact)
            parts.append(f'<ul style="margin:12px 0 0;padding-left:18px">{items}</ul>')
        if c.summary:
            parts.append(f'<p style="margin:12px 0 0"><b>What you talked about:</b> {_esc(c.summary)}</p>')
        for p in c.promises:
            parts.append(f'<p style="margin:8px 0 0"><b>Promised:</b> {_esc(p)}</p>')
        for n in c.notes:
            parts.append(f'<p style="margin:8px 0 0"><b>Your note:</b> {_esc(n)}</p>')
        for f in c.follow_ups:
            parts.append(f'<p style="margin:8px 0 0"><b>Follow up:</b> {_esc(f)}</p>')
        cards.append(
            '<div style="border:1px solid #eee;border-radius:16px;padding:24px;margin:16px 0">'
            + "".join(parts)
            + "</div>"
        )
    intro = (
        f"You met {count} {people} at {_esc(event_name)}. Here's who:"
        if count
        else f"Thanks for coming to {_esc(event_name)}! We didn't record any taps for you this time."
    )
    extra = ""
    if other_notes:
        items = "".join(f'<li style="margin:4px 0">{_esc(n)}</li>' for n in other_notes)
        extra += f'<p style="margin:24px 0 0;font-weight:600">Your other notes</p><ul style="margin:8px 0 0;padding-left:18px">{items}</ul>'
    if any(c.summary for c in connections):
        extra += '<p style="margin:24px 0 0;color:#555;font-size:13px">The recordings and transcripts behind these notes are now deleted.</p>'
    html_body = (
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'max-width:560px;margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.5">'
        f'<p style="font-size:16px">Hi {_esc(first_name)},</p>'
        f'<p style="font-size:16px">{intro}</p>'
        + "".join(cards)
        + extra
        + '<p style="margin-top:32px;color:#555">See you at the next one,<br>Tro</p></div>'
    )
    return subject, text, html_body

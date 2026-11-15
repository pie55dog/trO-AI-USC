"""Sending every attendee of an event their post-event email.

Attendees are the people with a bracelet assigned for the event. For each
one we look up their connections, show each connection's contact info
(only the fields that person chose to share), and send one email.

Every attempt is written to EmailLog, so running this twice doesn't
double-send (unless ``resend=True``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from . import mailer
from .config import Settings
from .connections import connected_people, shared_contact
from .models import BraceletAssignment, EmailLog, Event, Preferences, User, utcnow

# How each shareable field is labelled in the email.
FIELD_LABELS = {
    "email": "Email",
    "linkedin_url": "LinkedIn",
    "company": "Company",
    "website": "Website",
    "portfolio_url": "Portfolio",
    "instagram": "Instagram",
}


@dataclass
class SendReport:
    sent: int = 0
    skipped_already_sent: int = 0
    skipped_opted_out: int = 0
    skipped_no_email: int = 0
    failed: int = 0
    # "user <id>: <reason>" for each failure, so organizers can fix and re-run.
    failures: list[str] = field(default_factory=list)


def connection_entry(person: User, prefs: Preferences | None) -> mailer.ConnectionEntry:
    """How ``person`` appears in someone else's email."""
    contact = [(FIELD_LABELS[f], value) for f, value in shared_contact(person, prefs).items()]
    headline = person.position or " · ".join(p for p in (person.major, person.school) if p) or None
    return mailer.ConnectionEntry(name=person.name, contact=contact, headline=headline)


def connections_for(session: Session, event_id: int, user_id: int) -> list[mailer.ConnectionEntry]:
    """Everyone ``user_id`` connected with at the event, in tap order."""
    return [connection_entry(c.person, c.prefs) for c in connected_people(session, event_id, user_id)]


def send_event_emails(
    session: Session, settings: Settings, event: Event, *, resend: bool = False
) -> SendReport:
    """Send the post-event email to every attendee of ``event``."""
    report = SendReport()
    backend = mailer.get_backend(settings)

    attendees = session.exec(
        select(User)
        .join(BraceletAssignment, BraceletAssignment.user_id == User.id)
        .where(BraceletAssignment.event_id == event.id)
        .order_by(User.id)
    ).all()

    for user in attendees:
        prefs = session.get(Preferences, user.id)
        if prefs is not None and not prefs.summary_email_opt_in:
            report.skipped_opted_out += 1
            continue
        if not user.email:
            report.skipped_no_email += 1
            continue

        log = session.exec(
            select(EmailLog).where(EmailLog.event_id == event.id, EmailLog.user_id == user.id)
        ).first()
        if log is not None and log.status == "sent" and not resend:
            report.skipped_already_sent += 1
            continue

        subject, text, html_body = mailer.render_post_event_email(
            user.name, event.name, connections_for(session, event.id, user.id)
        )
        message = mailer.build_message(settings, user.email, subject, text, html_body)

        if log is None:
            log = EmailLog(event_id=event.id, user_id=user.id, to_address=user.email, status="pending")
        log.to_address = user.email
        log.sent_at = utcnow()
        try:
            backend.send(message)
        except mailer.EmailError as exc:
            log.status, log.error = "failed", str(exc)[:500]
            report.failed += 1
            report.failures.append(f"user {user.id}: {exc}")
        else:
            log.status, log.error = "sent", None
            report.sent += 1
        # Commit after each email so a crash midway still records who got one.
        session.add(log)
        session.commit()

    return report

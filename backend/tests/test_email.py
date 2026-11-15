"""Post-event emails and the email backends."""

from __future__ import annotations

import dataclasses
import smtplib

import pytest
from sqlmodel import select

from app import mailer
from app.models import Connection, EmailLog
from conftest import ADMIN, email_html, email_text, outbox


def attend(client, event_id, headers, bracelet):
    resp = client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": bracelet}, headers=headers)
    assert resp.status_code == 200


def connect(db, event_id, a, b):
    """Stand-in for bracelet processing, which will create these later."""
    lo, hi = sorted((a, b))
    db.add(Connection(event_id=event_id, user_a_id=lo, user_b_id=hi))
    db.commit()


def test_each_attendee_gets_one_email_listing_who_they_met(client, db, make_user, make_event, settings):
    event_id = make_event("Viterbi Industry Night")
    alice_id, alice = make_user(name="Alice Ng", email="alice@usc.edu")
    # Bob only shares his LinkedIn, not his email.
    bob_id, bob = make_user(name="Bob Lee", email="bob@usc.edu", shared_fields=["linkedin_url"])
    carol_id, carol = make_user(name="Carol Diaz", email="carol@usc.edu")
    for headers, bid in ((alice, "A1"), (bob, "B2"), (carol, "C3")):
        attend(client, event_id, headers, bid)
    connect(db, event_id, alice_id, bob_id)
    connect(db, event_id, alice_id, carol_id)

    resp = client.post(f"/events/{event_id}/send-summaries", headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json()["sent"] == 3

    mails = {m["To"]: m for m in outbox(settings)}
    assert set(mails) == {"alice@usc.edu", "bob@usc.edu", "carol@usc.edu"}

    alice_mail = mails["alice@usc.edu"]
    assert alice_mail["Subject"] == "Your connections from Viterbi Industry Night"
    text = email_text(alice_mail)
    assert "You met 2 people" in text
    assert "Bob Lee" in text and "Carol Diaz" in text
    assert "LinkedIn: https://linkedin.com/in/tommy" in text
    # Bob didn't share his email, so Alice doesn't see it.
    assert "bob@usc.edu" not in text
    # Carol shares everything by default.
    assert "carol@usc.edu" in text

    assert "You met 1 person" in email_text(mails["bob@usc.edu"])


def test_rerun_skips_already_sent_unless_resend(client, db, make_user, make_event, settings):
    event_id = make_event()
    _, h = make_user()
    attend(client, event_id, h, "A1")
    client.post(f"/events/{event_id}/send-summaries", headers=ADMIN)

    again = client.post(f"/events/{event_id}/send-summaries", headers=ADMIN).json()
    assert again["sent"] == 0 and again["skipped_already_sent"] == 1
    forced = client.post(f"/events/{event_id}/send-summaries", json={"resend": True}, headers=ADMIN).json()
    assert forced["sent"] == 1
    assert len(outbox(settings)) == 2


def test_opted_out_and_non_attendees_get_nothing(client, make_user, make_event, settings):
    event_id = make_event()
    _, opted_out = make_user(summary_email_opt_in=False)
    attend(client, event_id, opted_out, "A1")
    make_user()  # signed up but never claimed a bracelet for this event
    result = client.post(f"/events/{event_id}/send-summaries", headers=ADMIN).json()
    assert result["sent"] == 0 and result["skipped_opted_out"] == 1
    assert outbox(settings) == []


def test_attendee_with_no_taps_gets_a_friendly_email(client, make_user, make_event, settings):
    event_id = make_event("Club Mixer")
    _, h = make_user(name="Dana Park")
    attend(client, event_id, h, "A1")
    client.post(f"/events/{event_id}/send-summaries", headers=ADMIN)
    text = email_text(outbox(settings)[0])
    assert text.startswith("Hi Dana,")
    assert "didn't record any taps" in text


def test_user_text_is_escaped_in_html(client, db, make_user, make_event, settings):
    event_id = make_event()
    a_id, a = make_user(name="Alice")
    b_id, b = make_user(name='<img src=x onerror="alert(1)">')
    attend(client, event_id, a, "A1")
    attend(client, event_id, b, "B2")
    connect(db, event_id, a_id, b_id)
    client.post(f"/events/{event_id}/send-summaries", headers=ADMIN)
    alice_mail = next(m for m in outbox(settings) if m["To"] == "user1@usc.edu")
    html_body = email_html(alice_mail)
    assert "<img src=x" not in html_body
    assert "&lt;img src=x" in html_body


def test_send_failure_is_logged_and_retried_next_run(client, db, make_user, make_event, monkeypatch):
    event_id = make_event()
    user_id, h = make_user()
    attend(client, event_id, h, "A1")

    def boom(self, message):
        raise mailer.EmailError("SMTP down")

    monkeypatch.setattr(mailer.ConsoleBackend, "send", boom)
    result = client.post(f"/events/{event_id}/send-summaries", headers=ADMIN).json()
    assert result["failed"] == 1 and "SMTP down" in result["failures"][0]
    log = db.exec(select(EmailLog)).one()
    assert log.status == "failed"

    monkeypatch.undo()
    result = client.post(f"/events/{event_id}/send-summaries", headers=ADMIN).json()
    assert result["sent"] == 1
    db.expire_all()
    assert db.exec(select(EmailLog)).one().status == "sent"


def test_send_summaries_needs_admin(client, make_event):
    event_id = make_event()
    assert client.post(f"/events/{event_id}/send-summaries").status_code == 401


def test_smtp_not_configured_returns_503(client, app, make_event, settings):
    event_id = make_event()
    app.state.settings = dataclasses.replace(settings, email_backend="smtp", smtp_host="")
    resp = client.post(f"/events/{event_id}/send-summaries", headers=ADMIN)
    assert resp.status_code == 503


def test_admin_test_email(client, settings):
    resp = client.post("/admin/email/test", json={"to": "grace@usc.edu"}, headers=ADMIN)
    assert resp.status_code == 200
    assert outbox(settings)[0]["To"] == "grace@usc.edu"


# --- SMTP backend, with smtplib faked ------------------------------------------


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.calls: list[str] = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, message):
        self.calls.append(f"send:{message['To']}")


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_smtp_backend_uses_starttls_and_login(settings, fake_smtp):
    s = dataclasses.replace(
        settings, email_backend="smtp", smtp_host="smtp.gmail.com", smtp_port=587, smtp_username="tro@gmail.com"
    )
    msg = mailer.build_message(s, "x@usc.edu", "Hi", "text", "<p>html</p>")
    mailer.get_backend(s).send(msg)
    smtp = fake_smtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 587)
    assert smtp.calls == ["starttls", "login:tro@gmail.com", "send:x@usc.edu"]


def test_smtp_errors_become_email_error(settings, monkeypatch):
    def refuse(*a, **k):
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    s = dataclasses.replace(settings, email_backend="smtp", smtp_host="localhost")
    with pytest.raises(mailer.EmailError):
        mailer.get_backend(s).send(mailer.build_message(s, "x@usc.edu", "Hi", "t", "<p>h</p>"))

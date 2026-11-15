"""Organizer console: edit events, roster, check-in desk, overview counts."""

from __future__ import annotations

from app.models import Connection, EmailLog
from conftest import ADMIN


def test_organizer_endpoints_need_the_key(client, make_event):
    event_id = make_event()
    for method, path in [
        ("patch", f"/events/{event_id}"),
        ("get", f"/events/{event_id}/overview"),
        ("get", f"/events/{event_id}/attendees"),
        ("post", f"/events/{event_id}/attendees"),
        ("delete", f"/events/{event_id}/attendees/1"),
        ("get", "/admin/check"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path
    assert client.get("/admin/check", headers=ADMIN).json()["ok"] is True


def test_edit_event_changes_only_sent_fields(client, make_event):
    event_id = make_event()
    resp = client.patch(f"/events/{event_id}", json={"name": "  Spring Mixer "}, headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Spring Mixer"
    assert resp.json()["location"] == "Town & Gown"

    resp = client.patch(f"/events/{event_id}", json={"location": "", "starts_at": "2026-11-20T18:00:00Z"}, headers=ADMIN)
    assert resp.json()["location"] is None
    assert resp.json()["starts_at"].startswith("2026-11-20T18:00")

    assert client.patch(f"/events/{event_id}", json={"name": ""}, headers=ADMIN).status_code == 422
    assert client.patch("/events/999", json={"name": "x"}, headers=ADMIN).status_code == 404


def test_roster_lists_bracelet_holders_with_their_status(client, db, make_user, make_event):
    event_id = make_event()
    a, ha = make_user(name="Ada", consent=True)
    b, hb = make_user(name="Bo", consent=False, summary_email_opt_in=False)
    make_user(name="Not here")  # onboarded but never claimed a bracelet
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "aa01"}, headers=ha)
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "bb02"}, headers=hb)
    db.add(Connection(event_id=event_id, user_a_id=min(a, b), user_b_id=max(a, b), recorded=False))
    db.add(EmailLog(event_id=event_id, user_id=a, to_address="x@usc.edu", status="sent"))
    db.commit()

    roster = client.get(f"/events/{event_id}/attendees", headers=ADMIN).json()
    assert [p["name"] for p in roster] == ["Bo", "Ada"]  # newest check-in first
    ada = next(p for p in roster if p["name"] == "Ada")
    assert ada["bracelet_id"] == "AA01"
    assert ada["recording_consent"] is True
    assert ada["connections"] == 1
    assert ada["email_status"] == "sent"
    bo = next(p for p in roster if p["name"] == "Bo")
    assert bo["recording_consent"] is False and bo["summary_email_opt_in"] is False
    assert bo["email_status"] is None

    overview = client.get(f"/events/{event_id}/overview", headers=ADMIN).json()
    assert overview["event"]["id"] == event_id
    assert overview["attendees"] == 2
    assert overview["recording_consent"] == 1
    assert overview["summary_email_opt_in"] == 1
    assert overview["connections"] == 1
    assert overview["emails_sent"] == 1 and overview["emails_failed"] == 0


def test_desk_assign_by_email(client, make_user, make_event):
    event_id = make_event()
    make_user(name="Ada", email="ada@usc.edu")
    resp = client.post(
        f"/events/{event_id}/attendees", json={"email": " ADA@usc.edu ", "bracelet_id": "a4:cf:00:01"}, headers=ADMIN
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["bracelet_id"] == "A4CF0001"

    # Assigning again swaps their bracelet.
    resp = client.post(f"/events/{event_id}/attendees", json={"email": "ada@usc.edu", "bracelet_id": "a4cf0002"}, headers=ADMIN)
    assert resp.json()["bracelet_id"] == "A4CF0002"
    assert len(client.get(f"/events/{event_id}/attendees", headers=ADMIN).json()) == 1


def test_desk_assign_refusals(client, make_user, make_event):
    event_id = make_event()
    make_user(name="Ada", email="ada@usc.edu")
    make_user(name="Bo", email="bo@usc.edu")
    make_user(name="Half", email="half@usc.edu", onboarded=False)

    def assign(email, bid):
        return client.post(f"/events/{event_id}/attendees", json={"email": email, "bracelet_id": bid}, headers=ADMIN)

    assert assign("nobody@usc.edu", "1").status_code == 404
    half = assign("half@usc.edu", "1")
    assert half.status_code == 409 and "missing" in half.json()["detail"]
    assert assign("ada@usc.edu", "1").status_code == 201
    assert assign("bo@usc.edu", "1").status_code == 409  # Ada holds it
    assert assign("bo@usc.edu", "not valid!").status_code == 422


def test_release_bracelet_frees_it_for_someone_else(client, make_user, make_event):
    event_id = make_event()
    ada, _ = make_user(email="ada@usc.edu")
    make_user(email="bo@usc.edu")
    client.post(f"/events/{event_id}/attendees", json={"email": "ada@usc.edu", "bracelet_id": "7"}, headers=ADMIN)

    assert client.delete(f"/events/{event_id}/attendees/{ada}", headers=ADMIN).status_code == 204
    assert client.get(f"/events/{event_id}/attendees", headers=ADMIN).json() == []
    assert client.delete(f"/events/{event_id}/attendees/{ada}", headers=ADMIN).status_code == 404
    assert client.post(f"/events/{event_id}/attendees", json={"email": "bo@usc.edu", "bracelet_id": "7"}, headers=ADMIN).status_code == 201

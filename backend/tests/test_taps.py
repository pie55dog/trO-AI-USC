"""Live bracelet taps (POST /bracelets/tap), stars, and the bracelet status check."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from app import taps
from app.models import Connection, Star, TapReport, utcnow
from conftest import BRACELET, email_text, outbox


def _wear(client, make_user, event_id, bracelet, name, **kw):
    uid, headers = make_user(name=name, **kw)
    resp = client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": bracelet}, headers=headers)
    assert resp.status_code == 200, resp.text
    return uid, headers


def _tap(client, device, peer, **extra):
    return client.post("/bracelets/tap", json={"device": device, "peer": peer, "rssi": -30, **extra}, headers=BRACELET)


def test_tap_needs_bracelet_key(client):
    assert client.post("/bracelets/tap", json={"device": "TRO-1", "peer": "TRO-2"}).status_code == 401


def test_unlinked_bracelet_gets_409(client):
    resp = _tap(client, "TRO-1", "TRO-2")
    assert resp.status_code == 409
    assert "linked" in resp.json()["detail"]


def test_two_matching_reports_pair(client, make_user, make_event, db):
    event_id = make_event()
    alice, alice_h = _wear(client, make_user, event_id, "TRO-1", "Alice Ng")
    bob, bob_h = _wear(client, make_user, event_id, "TRO-2", "Bob Li")

    first = _tap(client, "TRO-1", "TRO-2")
    assert first.status_code == 200 and first.json()["status"] == "waiting"
    # Retrying before the other side reports refreshes the same report.
    assert _tap(client, "TRO-1", "TRO-2").json()["status"] == "waiting"
    assert len(db.exec(select(TapReport)).all()) == 1

    second = _tap(client, "tro-2", "tro-1").json()  # ids are normalized
    assert second["status"] == "paired"
    assert second["peer_name"] == "Alice Ng"
    # Same profile fixture -> same interests, major and school.
    assert second["match_pct"] == 99
    assert second["both_consented"] is True

    # Alice's next retry sees the pairing.
    again = _tap(client, "TRO-1", "TRO-2").json()
    assert again["status"] == "paired"
    assert again["session"] == second["session"]
    assert again["peer_name"] == "Bob Li"

    conns = db.exec(select(Connection)).all()
    assert len(conns) == 1 and conns[0].recorded is False

    # Both dashboards show the other person straight away.
    assert [c["name"] for c in client.get(f"/events/{event_id}/connections", headers=alice_h).json()] == ["Bob Li"]
    assert [c["name"] for c in client.get(f"/events/{event_id}/connections", headers=bob_h).json()] == ["Alice Ng"]


def test_one_sided_report_never_pairs(client, make_user, make_event, db):
    """Walking past someone (only one bracelet notices) must not connect you."""
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice")
    _wear(client, make_user, event_id, "TRO-2", "Bob")
    for _ in range(5):
        assert _tap(client, "TRO-1", "TRO-2").json()["status"] == "waiting"
    # Bob's bracelet was touching someone else.
    assert _tap(client, "TRO-2", "TRO-9").json()["status"] == "waiting"
    assert db.exec(select(Connection)).all() == []


def test_reports_too_far_apart_dont_pair(client, make_user, make_event, db):
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice")
    _wear(client, make_user, event_id, "TRO-2", "Bob")
    long_ago = utcnow() - taps.TAP_WINDOW - timedelta(seconds=5)
    assert taps.report_tap(db, "TRO1", "TRO2", now=long_ago).status == "waiting"
    assert _tap(client, "TRO-2", "TRO-1").json()["status"] == "waiting"


def test_manual_tap_pairs_with_any_report(client, make_user, make_event):
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice")
    _wear(client, make_user, event_id, "TRO-2", "Bob")
    assert _tap(client, "TRO-1", "").json()["status"] == "waiting"
    assert _tap(client, "TRO-2", "").json()["peer_name"] == "Alice"
    assert _tap(client, "TRO-1", "").json()["peer_name"] == "Bob"


def test_exact_match_beats_manual_tap(client, make_user, make_event):
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice")
    _wear(client, make_user, event_id, "TRO-2", "Bob")
    _wear(client, make_user, event_id, "TRO-3", "Cara")
    _tap(client, "TRO-3", "")  # Cara holds her button across the room
    _tap(client, "TRO-2", "TRO-1")
    assert _tap(client, "TRO-1", "TRO-2").json()["peer_name"] == "Bob"


def test_other_events_never_pair(client, make_user, make_event):
    e1, e2 = make_event("Night 1"), make_event("Night 2")
    _wear(client, make_user, e1, "TRO-1", "Alice")
    _wear(client, make_user, e2, "TRO-2", "Bob")
    _tap(client, "TRO-1", "")
    assert _tap(client, "TRO-2", "").json()["status"] == "waiting"


def test_tapping_again_reuses_the_connection(client, make_user, make_event, db):
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice")
    _wear(client, make_user, event_id, "TRO-2", "Bob")
    _tap(client, "TRO-1", "TRO-2")
    first = _tap(client, "TRO-2", "TRO-1").json()["connection_id"]
    # Expire those reports, then tap again later in the night.
    for r in db.exec(select(TapReport)).all():
        r.last_at = utcnow() - timedelta(minutes=5)
        db.add(r)
    db.commit()
    _tap(client, "TRO-1", "TRO-2")
    assert _tap(client, "TRO-2", "TRO-1").json()["connection_id"] == first
    assert len(db.exec(select(Connection)).all()) == 1


def test_match_pct_hidden_unless_both_opted_in(client, make_user, make_event):
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice", recommendations_opt_in=False)
    _wear(client, make_user, event_id, "TRO-2", "Bob")
    _tap(client, "TRO-1", "TRO-2")
    assert _tap(client, "TRO-2", "TRO-1").json()["match_pct"] is None


def test_match_pct_scores_overlap():
    from app.models import Preferences, User

    yes = Preferences(user_id=0, recommendations_opt_in=True)
    a = User(name="A", interests=["AI", "Hardware", "Music"], major="CS", school="USC")
    b = User(name="B", interests=["ai", "Film"], major="Film", school="USC")
    c = User(name="C", interests=["Golf"])
    assert taps.match_pct(a, b, yes, yes) == 30 + round(55 * 1 / 2) + 5
    assert taps.match_pct(a, c, yes, yes) == 30


def test_star_latest_connection(client, make_user, make_event, settings):
    event_id = make_event()
    alice, alice_h = _wear(client, make_user, event_id, "TRO-1", "Alice")
    _, bob_h = _wear(client, make_user, event_id, "TRO-2", "Bob")
    assert client.post("/bracelets/star", json={"device": "TRO-1"}, headers=BRACELET).json()["status"] == "no_connection"

    _tap(client, "TRO-1", "TRO-2")
    _tap(client, "TRO-2", "TRO-1")
    resp = client.post("/bracelets/star", json={"device": "TRO-1"}, headers=BRACELET).json()
    assert resp == {"status": "starred", "connection_id": resp["connection_id"], "peer_name": "Bob"}
    client.post("/bracelets/star", json={"device": "TRO-1"}, headers=BRACELET)  # twice is fine

    # Only Alice starred, so only her view shows it.
    assert client.get(f"/events/{event_id}/connections", headers=alice_h).json()[0]["starred"] is True
    assert client.get(f"/events/{event_id}/connections", headers=bob_h).json()[0]["starred"] is False

    assert client.post(f"/events/{event_id}/test-email", headers=alice_h).status_code == 200
    assert "★ Bob" in email_text(outbox(settings)[-1])


def test_star_unlinked_is_409(client):
    assert client.post("/bracelets/star", json={"device": "TRO-1"}, headers=BRACELET).status_code == 409


def test_status_before_and_after_claim(client, make_user, make_event):
    assert client.get("/bracelets/tro-1/status", headers=BRACELET).json() == {
        "bracelet_id": "TRO1",
        "linked": False,
        "event_id": None,
        "first_name": None,
        "recording_consent": None,
    }
    event_id = make_event()
    _wear(client, make_user, event_id, "TRO-1", "Alice Ng", consent=False)
    body = client.get("/bracelets/TRO-1/status", headers=BRACELET).json()
    assert body["linked"] is True and body["event_id"] == event_id
    assert body["first_name"] == "Alice" and body["recording_consent"] is False


def test_status_follows_newest_wearer(client, make_user, make_event):
    e1, e2 = make_event("Night 1"), make_event("Night 2")
    _wear(client, make_user, e1, "TRO-1", "Alice")
    _wear(client, make_user, e2, "TRO-1", "Bob")
    body = client.get("/bracelets/TRO-1/status", headers=BRACELET).json()
    assert (body["event_id"], body["first_name"]) == (e2, "Bob")


def test_deleting_account_removes_taps_and_stars(client, make_user, make_event, db):
    event_id = make_event()
    _, alice_h = _wear(client, make_user, event_id, "TRO-1", "Alice")
    _, bob_h = _wear(client, make_user, event_id, "TRO-2", "Bob")
    _tap(client, "TRO-1", "TRO-2")
    _tap(client, "TRO-2", "TRO-1")
    client.post("/bracelets/star", json={"device": "TRO-2"}, headers=BRACELET)  # Bob stars Alice
    assert client.delete("/users/me", headers=alice_h).status_code == 204
    db.expire_all()
    assert db.exec(select(Connection)).all() == []
    assert db.exec(select(Star)).all() == []
    assert db.exec(select(TapReport)).all() == []
    assert client.get(f"/events/{event_id}/connections", headers=bob_h).json() == []

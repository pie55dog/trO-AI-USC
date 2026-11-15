"""The phone mic: the attendee's phone records while the bracelets (no mic yet) do the taps.

Same pipeline as bracelet clips (tests/test_recordings.py), uploaded to
POST /events/{id}/recordings with the person's login instead of the bracelet key.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models import Connection, Recording
from test_recordings import FakeAI, _pair, _upload, _wear, two_clips


@pytest.fixture
def fake_ai(app):
    fake = FakeAI()
    app.state.ai_factory = lambda: fake
    return fake


@pytest.fixture
def pair(client, make_user, make_event):
    event_id = make_event()
    alice, alice_h = _wear(client, make_user, event_id, "TRO-1", "Alice Ng")
    bob, bob_h = _wear(client, make_user, event_id, "TRO-2", "Bob Li")
    conn = _pair(client)
    return dict(event=event_id, alice=alice, alice_h=alice_h, bob=bob, bob_h=bob_h, conn=conn)


def _phone(client, event_id, headers, data, kind="conversation", **params):
    return client.post(
        f"/events/{event_id}/recordings",
        params={"kind": kind, **params},
        content=data,
        headers={**headers, "Content-Type": "audio/wav"},
    )


def test_connections_tell_the_phone_what_to_record(client, pair, make_user, make_event):
    card = client.get(f"/events/{pair['event']}/connections", headers=pair["alice_h"]).json()[0]
    assert card["connection_id"] == pair["conn"]
    assert card["both_consented"] is True

    body = {"recording_consent": False, "recommendations_opt_in": True}
    assert client.put("/users/me/preferences", json=body, headers=pair["bob_h"]).status_code == 200
    card = client.get(f"/events/{pair['event']}/connections", headers=pair["alice_h"]).json()[0]
    assert card["both_consented"] is False


def test_two_phones_make_the_same_notes_as_two_bracelets(client, pair, fake_ai, db):
    clip_a, clip_b = two_clips(0.6)
    r1 = _phone(client, pair["event"], pair["alice_h"], clip_a, connection_id=pair["conn"], started_at=1_763_190_000_000)
    assert r1.status_code == 201, r1.text
    assert r1.json()["duration_s"] == pytest.approx(15.0)
    r2 = _phone(client, pair["event"], pair["bob_h"], clip_b, connection_id=pair["conn"], started_at=1_763_190_000_500)
    assert r2.status_code == 201, r2.text

    db.expire_all()
    recs = db.exec(select(Recording)).all()
    assert {r.bracelet_id for r in recs} == {"PHONE"}
    assert {r.status for r in recs} == {"done"}
    assert db.get(Connection, pair["conn"]).recorded is True
    notes = client.get(f"/events/{pair['event']}/notes/{pair['bob']}", headers=pair["alice_h"]).json()
    assert notes["conversation_status"] == "ready"
    assert notes["conversation"]["speaker_method"] == "two_bracelets"
    assert [line["speaker"] for line in notes["conversation"]["transcript"]] == ["you", "them", "you", "them", "you", "them"]


def test_one_phone_and_one_bracelet_mix(client, pair, fake_ai, db):
    clip_a, clip_b = two_clips(0.6)
    assert _phone(client, pair["event"], pair["alice_h"], clip_a, connection_id=pair["conn"]).status_code == 201
    assert _upload(client, "TRO-2", clip_b, connection_id=pair["conn"]).status_code == 201
    notes = client.get(f"/events/{pair['event']}/notes/{pair['alice']}", headers=pair["bob_h"]).json()
    assert notes["conversation_status"] == "ready"


def test_phone_respects_consent(client, pair, fake_ai, db):
    body = {"recording_consent": False, "recommendations_opt_in": True}
    assert client.put("/users/me/preferences", json=body, headers=pair["bob_h"]).status_code == 200
    resp = _phone(client, pair["event"], pair["alice_h"], two_clips()[0], connection_id=pair["conn"])
    assert resp.status_code == 403
    assert db.exec(select(Recording)).all() == []


def test_phone_voice_note(client, pair, fake_ai, db):
    resp = _phone(client, pair["event"], pair["alice_h"], two_clips()[0][:100_000], kind="voice_note")
    assert resp.status_code == 201, resp.text
    notes = client.get(f"/events/{pair['event']}/notes", headers=pair["alice_h"]).json()
    assert [n["text"] for n in notes["other"]] == ["Start a hardware club."]


def test_phone_upload_validation(client, pair, fake_ai, make_user, make_event):
    clip = two_clips()[0]
    ev = pair["event"]
    assert client.post(f"/events/{ev}/recordings", params={"kind": "voice_note"}, content=clip).status_code == 401
    assert _phone(client, ev, pair["alice_h"], clip).status_code == 422  # no connection_id
    assert _phone(client, ev, pair["alice_h"], clip, kind="song").status_code == 422
    assert _phone(client, ev, pair["alice_h"], b"", connection_id=pair["conn"]).status_code == 422
    assert _phone(client, 999, pair["alice_h"], clip, kind="voice_note").status_code == 404
    # Someone else's conversation, or a voice note without a bracelet at this event.
    _, cara_h = make_user(name="Cara Wu")
    assert _phone(client, ev, cara_h, clip, connection_id=pair["conn"]).status_code == 422
    assert _phone(client, ev, cara_h, clip, kind="voice_note").status_code == 409
    # A connection from another event doesn't count.
    other = make_event("Another night")
    assert _phone(client, other, pair["alice_h"], clip, connection_id=pair["conn"]).status_code == 422

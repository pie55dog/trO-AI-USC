"""Events, bracelet assignment, and the bracelet upload placeholder."""

from __future__ import annotations

import json

from sqlmodel import select

from app.models import BraceletUpload
from conftest import ADMIN, BRACELET


# --- Events -----------------------------------------------------------------


def test_only_organizers_create_events(client):
    assert client.post("/events", json={"name": "Mixer"}).status_code == 401
    assert client.post("/events", json={"name": "Mixer"}, headers={"X-Admin-Key": "wrong"}).status_code == 401
    resp = client.post("/events", json={"name": "Mixer"}, headers=ADMIN)
    assert resp.status_code == 201
    assert client.get("/events").json()[0]["name"] == "Mixer"


def test_admin_endpoints_disabled_when_key_unset(settings, fake_linkedin):
    import dataclasses

    from fastapi.testclient import TestClient

    from app.factory import create_app

    app = create_app(dataclasses.replace(settings, admin_api_key=""), fake_linkedin.client_factory())
    # Even an empty header must not get in when no key is configured.
    resp = TestClient(app).post("/events", json={"name": "x"}, headers={"X-Admin-Key": ""})
    assert resp.status_code == 503


def test_unknown_event_is_404(client):
    assert client.get("/events/999").status_code == 404


# --- Bracelet assignment ------------------------------------------------------


def test_claim_bracelet_normalizes_id(client, make_user, make_event):
    _, headers = make_user()
    event_id = make_event()
    resp = client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "a4:cf:12:9b:00:1e"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["bracelet_id"] == "A4CF129B001E"
    assert client.get(f"/events/{event_id}/bracelet", headers=headers).json()["bracelet_id"] == "A4CF129B001E"


def test_claim_requires_finished_onboarding(client, make_user, make_event):
    _, headers = make_user(onboarded=False)
    resp = client.post(f"/events/{make_event()}/bracelet", json={"bracelet_id": "AA"}, headers=headers)
    assert resp.status_code == 409
    assert "recording_consent" in resp.json()["detail"]["missing"]


def test_bracelet_cannot_be_double_assigned(client, make_user, make_event):
    event_id = make_event()
    _, alice = make_user(name="Alice")
    _, bob = make_user(name="Bob")
    assert client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA-01"}, headers=alice).status_code == 200
    assert client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "aa01"}, headers=bob).status_code == 409


def test_same_bracelet_reusable_across_events(client, make_user, make_event):
    _, alice = make_user(name="Alice")
    _, bob = make_user(name="Bob")
    e1, e2 = make_event("Night 1"), make_event("Night 2")
    assert client.post(f"/events/{e1}/bracelet", json={"bracelet_id": "AA01"}, headers=alice).status_code == 200
    assert client.post(f"/events/{e2}/bracelet", json={"bracelet_id": "AA01"}, headers=bob).status_code == 200


def test_reclaim_swaps_bracelet(client, make_user, make_event):
    _, headers = make_user()
    event_id = make_event()
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA01"}, headers=headers)
    resp = client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "BB02"}, headers=headers)
    assert resp.json()["bracelet_id"] == "BB02"
    # The old bracelet is free again.
    _, other = make_user(name="Other")
    assert client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA01"}, headers=other).status_code == 200


def test_bad_bracelet_id_rejected(client, make_user, make_event):
    _, headers = make_user()
    resp = client.post(f"/events/{make_event()}/bracelet", json={"bracelet_id": "<script>"}, headers=headers)
    assert resp.status_code == 422


# --- Bracelet uploads (placeholder: store only) -------------------------------


def test_upload_needs_bracelet_key(client):
    assert client.post("/bracelets/uploads", data={"bracelet_id": "AA"}).status_code == 401


def test_upload_is_stored_untouched_and_linked_to_attendee(client, db, make_user, make_event, settings):
    user_id, headers = make_user()
    event_id = make_event()
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA:01"}, headers=headers)

    payload = {"taps": [{"peer": "BB02", "t": 1731640000}]}
    resp = client.post(
        "/bracelets/uploads",
        data={"bracelet_id": "aa-01", "payload": json.dumps(payload)},
        files=[
            ("files", ("../../convo.wav", b"RIFF-convo", "audio/wav")),
            ("files", ("note.wav", b"RIFF-note", "audio/wav")),
        ],
        headers=BRACELET,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {
        "id": body["id"],
        "bracelet_id": "AA01",
        "event_id": event_id,
        "user_id": user_id,
        "status": "received",  # not processed: that's the hardware/AI follow-up
        "files": 2,
    }

    upload = db.exec(select(BraceletUpload)).one()
    assert upload.payload == payload
    # File names are sanitized; "../" can't escape the upload folder.
    assert all(p.startswith(f"uploads/{upload.id}/") for p in upload.file_paths)
    assert (settings.media_dir / upload.file_paths[0]).read_bytes() == b"RIFF-convo"


def test_upload_from_unassigned_bracelet_is_kept(client, db):
    resp = client.post("/bracelets/uploads", data={"bracelet_id": "FFFF"}, headers=BRACELET)
    assert resp.status_code == 201
    assert resp.json()["user_id"] is None and resp.json()["event_id"] is None


def test_upload_rejects_bad_json_and_cleans_up(client, db):
    resp = client.post("/bracelets/uploads", data={"bracelet_id": "AA", "payload": "{not json"}, headers=BRACELET)
    assert resp.status_code == 422
    assert db.exec(select(BraceletUpload)).all() == []


def test_upload_with_explicit_event_picks_that_assignment(client, make_user, make_event):
    _, alice = make_user(name="Alice")
    _, bob = make_user(name="Bob")
    e1, e2 = make_event("Night 1"), make_event("Night 2")
    client.post(f"/events/{e1}/bracelet", json={"bracelet_id": "AA01"}, headers=alice)
    client.post(f"/events/{e2}/bracelet", json={"bracelet_id": "AA01"}, headers=bob)
    resp = client.post("/bracelets/uploads", data={"bracelet_id": "AA01", "event_id": str(e1)}, headers=BRACELET)
    assert resp.json()["event_id"] == e1


def test_upload_for_known_event_without_assignment_keeps_event(client, make_event):
    event_id = make_event()
    resp = client.post("/bracelets/uploads", data={"bracelet_id": "FFFF", "event_id": str(event_id)}, headers=BRACELET)
    assert resp.json()["event_id"] == event_id and resp.json()["user_id"] is None


def test_oversized_upload_file_is_rejected_and_cleaned_up(client, db, settings, monkeypatch):
    from app.routers import bracelets as bracelet_router

    monkeypatch.setattr(bracelet_router, "MAX_FILE_BYTES", 10)
    resp = client.post(
        "/bracelets/uploads",
        data={"bracelet_id": "AA"},
        files=[("files", ("big.wav", b"x" * 11, "audio/wav"))],
        headers=BRACELET,
    )
    assert resp.status_code == 413
    assert db.exec(select(BraceletUpload)).all() == []
    assert not any((settings.media_dir / "uploads").iterdir())


def test_reused_bracelet_upload_must_name_its_event(client, make_user, make_event):
    """Guessing the event could tie Alice's audio to Bob, so we refuse to guess."""
    _, alice = make_user(name="Alice")
    _, bob = make_user(name="Bob")
    e1, e2 = make_event("Night 1"), make_event("Night 2")
    client.post(f"/events/{e1}/bracelet", json={"bracelet_id": "AA01"}, headers=alice)
    client.post(f"/events/{e2}/bracelet", json={"bracelet_id": "AA01"}, headers=bob)
    resp = client.post("/bracelets/uploads", data={"bracelet_id": "AA01"}, headers=BRACELET)
    assert resp.status_code == 422
    assert "event_id" in resp.json()["detail"]


# --- Dashboard connections ----------------------------------------------------


def test_connections_show_shared_fields_and_recording_status(client, db, make_user, make_event):
    from app.models import Connection

    event_id = make_event()
    me_id, me = make_user(name="Me", consent=True)
    a_id, _ = make_user(name="Alice", consent=True, shared_fields=["linkedin_url"])
    b_id, _ = make_user(name="Bob", consent=False)
    db.add(Connection(event_id=event_id, user_a_id=me_id, user_b_id=a_id, recorded=True))
    db.add(Connection(event_id=event_id, user_a_id=me_id, user_b_id=b_id))
    db.commit()

    people = {p["name"]: p for p in client.get(f"/events/{event_id}/connections", headers=me).json()}
    assert people["Alice"]["recorded"] is True
    assert people["Alice"]["contact"] == {"linkedin_url": "https://linkedin.com/in/tommy"}
    assert people["Bob"]["recorded"] is False  # Bob said no, so it was contact-only
    assert "email" in people["Bob"]["contact"]


def test_connections_empty_and_auth(client, make_user, make_event):
    event_id = make_event()
    _, me = make_user()
    assert client.get(f"/events/{event_id}/connections", headers=me).json() == []
    assert client.get(f"/events/{event_id}/connections").status_code == 401
    assert client.get("/events/999/connections", headers=me).status_code == 404


def test_recorded_is_what_happened_not_current_consent(client, db, make_user, make_event):
    """Changing consent after the event must not rewrite what was recorded."""
    from app.models import Connection

    event_id = make_event()
    me_id, me = make_user(consent=True)
    other_id, other = make_user(name="Other", consent=True)
    db.add(Connection(event_id=event_id, user_a_id=me_id, user_b_id=other_id, recorded=True))
    db.commit()
    client.put("/users/me/preferences", json={"recording_consent": False, "recommendations_opt_in": True}, headers=other)
    assert client.get(f"/events/{event_id}/connections", headers=me).json()[0]["recorded"] is True

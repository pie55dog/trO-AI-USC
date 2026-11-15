"""Onboarding: profile fields, preferences/consent, photos, account deletion."""

from __future__ import annotations

from sqlmodel import select

from app.models import BraceletUpload, Preferences, User
from conftest import ADMIN, BRACELET, COMPLETE_PROFILE, JPEG_BYTES, PNG_BYTES


def test_onboarding_completes_after_profile_and_consent(client, make_user):
    _, headers = make_user(onboarded=False)
    me = client.get("/users/me", headers=headers).json()
    assert me["onboarding"] == {
        "complete": False,
        "missing": ["school", "major", "interests", "recording_consent", "recommendations_opt_in"],
    }

    client.patch("/users/me", json=COMPLETE_PROFILE, headers=headers)
    me = client.get("/users/me", headers=headers).json()
    assert me["onboarding"]["missing"] == ["recording_consent", "recommendations_opt_in"]
    # Consent is undecided (None), not silently false.
    assert me["preferences"]["recording_consent"] is None

    client.put("/users/me/preferences", json={"recording_consent": False, "recommendations_opt_in": True}, headers=headers)
    me = client.get("/users/me", headers=headers).json()
    assert me["onboarding"] == {"complete": True, "missing": []}
    assert me["preferences"]["recording_consent"] is False


def test_profile_fields_are_cleaned(client, make_user):
    _, headers = make_user(onboarded=False)
    resp = client.patch(
        "/users/me",
        json={
            "school": "  USC  ",
            "interests": ["AI", " ai ", "", "Design"],
            "linkedin_url": "linkedin.com/in/tommy",
            "website": "",
            "email": "New@USC.edu",
        },
        headers=headers,
    )
    p = resp.json()["profile"]
    assert p["school"] == "USC"
    assert p["interests"] == ["AI", "Design"]
    assert p["linkedin_url"] == "https://linkedin.com/in/tommy"
    assert p["website"] is None
    assert p["email"] == "new@usc.edu"


def test_profile_rejects_bad_input(client, make_user):
    _, headers = make_user(onboarded=False)
    assert client.patch("/users/me", json={"website": "javascript:alert(1)"}, headers=headers).status_code == 422
    assert client.patch("/users/me", json={"email": "not-an-email"}, headers=headers).status_code == 422
    assert client.patch("/users/me", json={"name": "   "}, headers=headers).status_code == 422
    assert client.patch("/users/me", json={"bio": "x" * 1001}, headers=headers).status_code == 422


def test_email_must_be_unique(client, make_user):
    make_user(email="taken@usc.edu")
    _, headers = make_user(onboarded=False)
    resp = client.patch("/users/me", json={"email": "Taken@usc.edu"}, headers=headers)
    assert resp.status_code == 409


def test_preferences_require_explicit_consent(client, make_user):
    _, headers = make_user(onboarded=False)
    assert client.put("/users/me/preferences", json={}, headers=headers).status_code == 422
    assert client.put("/users/me/preferences", json={"recording_consent": None}, headers=headers).status_code == 422


def test_preferences_validate_shared_fields(client, make_user):
    _, headers = make_user(onboarded=False)
    bad = client.put(
        "/users/me/preferences", json={"recording_consent": True, "recommendations_opt_in": True, "shared_fields": ["ssn"]}, headers=headers
    )
    assert bad.status_code == 422
    ok = client.put(
        "/users/me/preferences",
        json={"recording_consent": True, "recommendations_opt_in": True, "shared_fields": ["instagram", "email", "email"]},
        headers=headers,
    )
    assert ok.json()["preferences"]["shared_fields"] == ["email", "instagram"]


def test_consent_timestamp_only_changes_when_answer_changes(client, make_user):
    _, headers = make_user(onboarded=False)
    first = client.put("/users/me/preferences", json={"recording_consent": True, "recommendations_opt_in": True}, headers=headers).json()
    same = client.put(
        "/users/me/preferences", json={"recording_consent": True, "recommendations_opt_in": True, "summary_email_opt_in": False}, headers=headers
    ).json()
    assert same["preferences"]["recording_consent_updated_at"] == first["preferences"]["recording_consent_updated_at"]
    changed = client.put("/users/me/preferences", json={"recording_consent": False, "recommendations_opt_in": True}, headers=headers).json()
    assert changed["preferences"]["recording_consent_updated_at"] != first["preferences"]["recording_consent_updated_at"]


def test_photo_upload_replaces_old_file(client, make_user, settings):
    _, headers = make_user()
    first = client.post("/users/me/photo", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers)
    url1 = first.json()["profile"]["photo_url"]
    second = client.post("/users/me/photo", files={"file": ("b.png", PNG_BYTES, "image/png")}, headers=headers)
    url2 = second.json()["profile"]["photo_url"]
    assert url1 != url2 and url2.endswith(".png")
    assert client.get(url1).status_code == 404  # old file removed
    assert client.get(url2).content == PNG_BYTES


def test_photo_upload_rejects_non_images_and_huge_files(client, make_user):
    _, headers = make_user()
    fake = client.post("/users/me/photo", files={"file": ("x.jpg", b"GIF89a....", "image/jpeg")}, headers=headers)
    assert fake.status_code == 422
    huge = JPEG_BYTES + b"\x00" * (5 * 1024 * 1024)
    big = client.post("/users/me/photo", files={"file": ("x.jpg", huge, "image/jpeg")}, headers=headers)
    assert big.status_code == 422


def test_photo_path_traversal_is_blocked(client):
    assert client.get("/media/photos/..%2F..%2Ftest.db").status_code == 404
    assert client.get("/media/photos/nope.jpg").status_code == 404


def test_delete_account_removes_everything(client, db, make_user, make_event, settings):
    user_id, headers = make_user()
    client.post("/users/me/photo", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers)
    event_id = make_event()
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA:BB"}, headers=headers)
    client.post(
        "/bracelets/uploads",
        data={"bracelet_id": "AABB"},
        files=[("files", ("talk.wav", b"RIFF-audio", "audio/wav"))],
        headers=BRACELET,
    )
    upload = db.exec(select(BraceletUpload)).one()
    audio = settings.media_dir / upload.file_paths[0]
    assert audio.exists()

    assert client.delete("/users/me", headers=headers).status_code == 204
    db.expire_all()
    assert db.get(User, user_id) is None
    assert db.get(Preferences, user_id) is None
    assert db.exec(select(BraceletUpload)).all() == []
    assert not audio.exists()
    assert not any((settings.media_dir / "photos").iterdir())
    assert client.get("/users/me", headers=headers).status_code == 401
    # The event itself is untouched.
    assert client.get(f"/events/{event_id}", headers=ADMIN).status_code == 200


def test_empty_email_clears_it(client, make_user):
    _, headers = make_user(onboarded=False)
    me = client.patch("/users/me", json={"email": ""}, headers=headers).json()
    assert me["profile"]["email"] is None
    assert "email" in me["onboarding"]["missing"]


def test_deleted_users_token_never_reaches_a_new_account(client, db, make_user):
    """User ids aren't reused, so an old token can't sign in as someone new."""
    from app.models import User

    _, headers = make_user()
    old_id, old_headers = make_user()  # the newest user: its id would be reused without AUTOINCREMENT
    client.delete("/users/me", headers=old_headers)
    newcomer = User(name="New Person", email="new@usc.edu")
    db.add(newcomer)
    db.commit()
    assert newcomer.id != old_id
    assert client.get("/users/me", headers=old_headers).status_code == 401


def test_delete_account_removes_upload_folders(client, db, make_user, make_event, settings):
    _, headers = make_user()
    event_id = make_event()
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA01"}, headers=headers)
    client.post(
        "/bracelets/uploads",
        data={"bracelet_id": "AA01"},
        files=[("files", ("a.wav", b"RIFF", "audio/wav"))],
        headers=BRACELET,
    )
    client.delete("/users/me", headers=headers)
    assert list((settings.media_dir / "uploads").iterdir()) == []


def test_recommendations_answer_is_required(client, make_user):
    _, headers = make_user(onboarded=False)
    resp = client.put("/users/me/preferences", json={"recording_consent": True}, headers=headers)
    assert resp.status_code == 422


def test_position_is_saved_and_trimmed(client, make_user):
    _, headers = make_user(onboarded=False)
    p = client.patch("/users/me", json={"position": "  SWE intern at Snap "}, headers=headers).json()["profile"]
    assert p["position"] == "SWE intern at Snap"


def test_sign_up_without_linkedin(client):
    resp = client.post("/users", json={"name": " Dana Park ", "email": "Dana@USC.edu"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["me"]["profile"]["name"] == "Dana Park"
    assert body["me"]["profile"]["email"] == "dana@usc.edu"
    me = client.get("/users/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200


def test_sign_up_refuses_existing_email(client, make_user):
    make_user(email="taken@usc.edu")
    assert client.post("/users", json={"name": "X", "email": "TAKEN@usc.edu"}).status_code == 409
    assert client.post("/users", json={"name": "", "email": "new@usc.edu"}).status_code == 422

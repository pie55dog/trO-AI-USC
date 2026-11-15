"""LinkedIn sign-in flow, with LinkedIn faked."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlmodel import select

from app.models import User
from conftest import JPEG_BYTES, auth_header


def start_login(client):
    """Hit /login and return the state LinkedIn would echo back."""
    resp = client.get("/auth/linkedin/login", follow_redirects=False)
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://www.linkedin.com/oauth/v2/authorization"
    query = parse_qs(location.query)
    assert query["scope"] == ["openid profile email"]
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://api.tro.test/auth/linkedin/callback"]
    return query["state"][0]


def finish_login(client, state, code="good-code"):
    resp = client.get(f"/auth/linkedin/callback?code={code}&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert location.netloc == "app.tro.test" and location.path == "/auth/callback"
    return {k: v[0] for k, v in parse_qs(location.fragment).items()}


def test_new_user_gets_name_email_and_photo_from_linkedin(client, db):
    params = finish_login(client, start_login(client))
    assert params["new_user"] == "1"

    me = client.get("/users/me", headers={"Authorization": f"Bearer {params['token']}"}).json()
    assert me["profile"]["name"] == "Tommy Trojan"
    assert me["profile"]["email"] == "tommy@usc.edu"  # lowercased
    assert me["profile"]["photo_url"].startswith("/media/photos/")
    # Bio isn't available from LinkedIn, so onboarding still asks for it.
    assert "bio" in me["onboarding"]["missing"]
    assert "recording_consent" in me["onboarding"]["missing"]

    # The photo was copied to our storage and is served back byte-for-byte.
    photo = client.get(me["profile"]["photo_url"])
    assert photo.status_code == 200 and photo.content == JPEG_BYTES
    assert photo.headers["content-type"] == "image/jpeg"


def test_returning_user_keeps_their_edits(client, db, fake_linkedin):
    token = finish_login(client, start_login(client))["token"]
    client.patch("/users/me", json={"name": "Tommy T.", "email": "tt@usc.edu"}, headers={"Authorization": f"Bearer {token}"})

    fake_linkedin.userinfo["name"] = "Changed On LinkedIn"
    params = finish_login(client, start_login(client))
    assert params["new_user"] == "0"
    me = client.get("/users/me", headers={"Authorization": f"Bearer {params['token']}"}).json()
    assert me["profile"]["name"] == "Tommy T."
    assert me["profile"]["email"] == "tt@usc.edu"
    assert len(db.exec(select(User)).all()) == 1


def test_callback_rejects_missing_or_wrong_state(client):
    # No cookie at all (callback not started by this browser).
    resp = client.get("/auth/linkedin/callback?code=x&state=forged", follow_redirects=False)
    assert "error=state" in resp.headers["location"]

    # Cookie present but state doesn't match.
    start_login(client)
    resp = client.get("/auth/linkedin/callback?code=x&state=forged", follow_redirects=False)
    assert "error=state" in resp.headers["location"]


def test_user_cancelled_on_linkedin(client):
    start_login(client)
    resp = client.get("/auth/linkedin/callback?error=user_cancelled_login", follow_redirects=False)
    assert resp.headers["location"].endswith("#error=cancelled")


def test_linkedin_token_failure_redirects_with_error(client, fake_linkedin):
    fake_linkedin.token_status = 400
    params = finish_login(client, start_login(client))
    assert params == {"error": "linkedin"}


def test_unverified_email_is_not_claimed(client, fake_linkedin):
    fake_linkedin.userinfo["email_verified"] = False
    token = finish_login(client, start_login(client))["token"]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["profile"]["email"] is None
    assert "email" in me["onboarding"]["missing"]


def test_bad_picture_does_not_block_sign_in(client, fake_linkedin):
    fake_linkedin.picture_bytes = b"<html>not an image</html>"
    token = finish_login(client, start_login(client))["token"]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["profile"]["photo_url"] is None


def test_picture_from_non_linkedin_host_is_never_fetched(client, fake_linkedin):
    fake_linkedin.userinfo["picture"] = "https://evil.example.com/x.jpg"
    finish_login(client, start_login(client))
    assert not any("evil.example.com" in str(r.url) for r in fake_linkedin.requests)


def test_login_disabled_without_linkedin_credentials(settings, fake_linkedin):
    import dataclasses

    from fastapi.testclient import TestClient

    from app.factory import create_app

    app = create_app(dataclasses.replace(settings, linkedin_client_id=""), fake_linkedin.client_factory())
    resp = TestClient(app).get("/auth/linkedin/login", follow_redirects=False)
    assert resp.status_code == 503


def test_protected_endpoints_need_a_valid_token(client, settings):
    assert client.get("/users/me").status_code == 401
    assert client.get("/users/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    # A well-signed token for a user that doesn't exist.
    assert client.get("/users/me", headers=auth_header(settings, 999)).status_code == 401


def test_oversized_picture_is_skipped(client, fake_linkedin):
    from app import linkedin

    fake_linkedin.picture_bytes = JPEG_BYTES + b"\x00" * (linkedin.MAX_PICTURE_BYTES + 1)
    token = finish_login(client, start_login(client))["token"]
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["profile"]["photo_url"] is None


def test_linkedin_reclaims_account_made_without_linkedin(client, db):
    """Someone who signed up by email (or had their email taken) gets that account back via a verified LinkedIn email."""
    made = client.post("/users", json={"name": "Typed Name", "email": "tommy@usc.edu"}).json()
    params = finish_login(client, start_login(client))
    assert params["new_user"] == "0"
    me = client.get("/users/me", headers={"Authorization": f"Bearer {params['token']}"}).json()
    assert me["profile"]["id"] == made["me"]["profile"]["id"]
    assert me["profile"]["email"] == "tommy@usc.edu"
    assert len(db.exec(select(User)).all()) == 1


def test_email_of_another_linkedin_account_is_not_claimed(client, db, fake_linkedin):
    first = finish_login(client, start_login(client))
    fake_linkedin.userinfo["sub"] = "someone-else"
    second = finish_login(client, start_login(client))
    me = client.get("/users/me", headers={"Authorization": f"Bearer {second['token']}"}).json()
    assert second["new_user"] == "1" and me["profile"]["email"] is None
    assert first["token"] != second["token"]

"""Shared test setup.

Each test gets its own temporary SQLite database and media folder, a fake
LinkedIn (no network), and the console email backend writing to a temp
outbox. Nothing here hits the real internet.
"""

from __future__ import annotations

import dataclasses
import json
import os
from email import message_from_bytes, policy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Settings
from app.factory import create_app
from app.security import issue_token

ADMIN_KEY = "test-admin-key"
BRACELET_KEY = "test-bracelet-key"

# Smallest valid PNG / JPEG headers (enough for our signature check).
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class FakeLinkedIn:
    """Stands in for LinkedIn's token, userinfo and picture endpoints."""

    def __init__(self):
        self.userinfo = {
            "sub": "li-abc123",
            "name": "Tommy Trojan",
            "given_name": "Tommy",
            "family_name": "Trojan",
            "picture": "https://media.licdn.com/dms/image/tommy.jpg",
            "locale": "en-US",
            "email": "Tommy@USC.edu",
            "email_verified": True,
        }
        self.token_status = 200
        self.picture_bytes = JPEG_BYTES
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith("https://www.linkedin.com/oauth/v2/accessToken"):
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 3600})
        if url.startswith("https://api.linkedin.com/v2/userinfo"):
            assert request.headers["Authorization"] == "Bearer fake-token"
            return httpx.Response(200, json=self.userinfo)
        if "licdn.com" in url:
            return httpx.Response(200, content=self.picture_bytes)
        return httpx.Response(404)

    def client_factory(self):
        return lambda: httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return dataclasses.replace(
        Settings(),
        # Set TEST_DATABASE_URL to run the suite against Postgres instead.
        database_url=os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="test-secret",
        media_dir=tmp_path / "media",
        frontend_url="https://app.tro.test",
        linkedin_client_id="client-id",
        linkedin_client_secret="client-secret",
        linkedin_redirect_uri="https://api.tro.test/auth/linkedin/callback",
        admin_api_key=ADMIN_KEY,
        bracelet_api_key=BRACELET_KEY,
        email_backend="console",
        email_from="Tro <no-reply@tro.test>",
    )


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from app import ratelimit

    ratelimit.reset_all()
    yield


@pytest.fixture
def fake_linkedin() -> FakeLinkedIn:
    return FakeLinkedIn()


@pytest.fixture
def app(settings, fake_linkedin):
    app = create_app(settings, http_client_factory=fake_linkedin.client_factory())
    yield app
    if os.environ.get("TEST_DATABASE_URL"):
        # A shared Postgres database outlives the test: start the next one empty.
        from sqlmodel import SQLModel

        SQLModel.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, base_url="https://api.tro.test")


@pytest.fixture
def db(app):
    with Session(app.state.engine) as session:
        yield session


def auth_header(settings: Settings, user_id: int) -> dict:
    return {"Authorization": f"Bearer {issue_token(settings, user_id)}"}


ADMIN = {"X-Admin-Key": ADMIN_KEY}
BRACELET = {"X-Bracelet-Key": BRACELET_KEY}

COMPLETE_PROFILE = {
    "school": "USC Viterbi",
    "major": "Computer Science",
    "bio": "I build things with microcontrollers.",
    "interests": ["Hardware", "AI"],
    "linkedin_url": "linkedin.com/in/tommy",
    "company": "Trojan Labs",
}


@pytest.fixture
def make_user(client, db, settings):
    """Create a user directly and optionally finish their onboarding.

    Returns (user_id, headers).
    """
    from app.models import User

    counter = {"n": 0}

    def _make(name="Tommy Trojan", email=None, onboarded=True, consent=True, **prefs):
        counter["n"] += 1
        user = User(name=name, email=email or f"user{counter['n']}@usc.edu", linkedin_sub=f"sub-{counter['n']}")
        db.add(user)
        db.commit()
        db.refresh(user)
        headers = auth_header(settings, user.id)
        if onboarded:
            assert client.patch("/users/me", json=COMPLETE_PROFILE, headers=headers).status_code == 200
            body = {"recording_consent": consent, "recommendations_opt_in": True, **prefs}
            assert client.put("/users/me/preferences", json=body, headers=headers).status_code == 200
        return user.id, headers

    return _make


@pytest.fixture
def make_event(client):
    def _make(name="Viterbi Industry Night"):
        resp = client.post("/events", json={"name": name, "location": "Town & Gown"}, headers=ADMIN)
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    return _make


def outbox(settings: Settings) -> list:
    """Emails the console backend wrote, parsed, oldest first."""
    folder = settings.media_dir / "outbox"
    if not folder.exists():
        return []
    return [
        message_from_bytes(p.read_bytes(), policy=policy.default) for p in sorted(folder.glob("*.eml"))
    ]


def email_text(msg) -> str:
    return msg.get_body(preferencelist=("plain",)).get_content()


def email_html(msg) -> str:
    return msg.get_body(preferencelist=("html",)).get_content()


def as_json(obj) -> str:
    return json.dumps(obj)

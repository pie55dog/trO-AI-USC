"""Settings used when hosting on Render's free tier.

* MEDIA_IN_DB: the disk is wiped on every restart, so stored files also get
  a copy in the database and come back from it.
* EMAIL_BACKEND=apps_script: SMTP ports are blocked, so email goes over https
  to a Google Apps Script relay.
* Postgres URLs from the host are switched to the installed psycopg driver.
"""

from __future__ import annotations

import dataclasses
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app import mailer
from app.db import normalize_database_url
from app.factory import create_app
from app.models import BraceletUpload, MediaFile

from conftest import BRACELET, JPEG_BYTES, PNG_BYTES


@pytest.fixture
def settings(settings):
    return dataclasses.replace(settings, media_in_db=True)


def test_photo_comes_back_after_the_disk_is_wiped(client, db, make_user, settings):
    _, headers = make_user()
    me = client.post("/users/me/photo", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers).json()
    url = me["profile"]["photo_url"]

    shutil.rmtree(settings.media_dir)  # what a restart on Render does
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.content == JPEG_BYTES


def test_replacing_a_photo_drops_the_old_copy(client, db, make_user):
    _, headers = make_user()
    client.post("/users/me/photo", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers)
    me = client.post("/users/me/photo", files={"file": ("b.png", PNG_BYTES, "image/png")}, headers=headers).json()
    db.expire_all()
    paths = [m.path for m in db.exec(select(MediaFile)).all()]
    assert paths == [me["profile"]["photo_url"].removeprefix("/media/")]


def test_uploads_are_copied_and_deleted_with_the_account(client, db, make_user, make_event):
    _, headers = make_user()
    client.post("/users/me/photo", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers)
    event_id = make_event()
    client.post(f"/events/{event_id}/bracelet", json={"bracelet_id": "AA02"}, headers=headers)
    client.post(
        "/bracelets/uploads",
        data={"bracelet_id": "AA02"},
        files=[("files", ("talk.wav", b"RIFF-audio", "audio/wav"))],
        headers=BRACELET,
    )
    upload = db.exec(select(BraceletUpload)).one()
    copy = db.get(MediaFile, upload.file_paths[0])
    assert copy is not None and copy.data == b"RIFF-audio"

    assert client.delete("/users/me", headers=headers).status_code == 204
    db.expire_all()
    assert db.exec(select(MediaFile)).all() == []


def test_copies_are_off_by_default(tmp_path, settings, fake_linkedin, make_user):
    plain = dataclasses.replace(settings, media_in_db=False, database_url=f"sqlite:///{tmp_path / 'plain.db'}")
    app = create_app(plain, http_client_factory=fake_linkedin.client_factory())
    from sqlmodel import Session

    with TestClient(app, base_url="https://api.tro.test") as c, Session(app.state.engine) as s:
        from app.models import User
        from app.security import issue_token

        user = User(name="A", email="a@usc.edu")
        s.add(user)
        s.commit()
        headers = {"Authorization": f"Bearer {issue_token(plain, user.id, 0)}"}
        assert c.post("/users/me/photo", files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")}, headers=headers).status_code == 200
        assert s.exec(select(MediaFile)).all() == []
    app.state.engine.dispose()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
        ("sqlite:///./tro.db", "sqlite:///./tro.db"),
    ],
)
def test_postgres_urls_use_psycopg(given, expected):
    assert normalize_database_url(given) == expected


def _relay_settings(settings, **kw):
    return dataclasses.replace(
        settings,
        email_backend="apps_script",
        email_relay_url="https://script.google.com/macros/s/abc/exec",
        email_relay_key="relay-key",
        **kw,
    )


def test_apps_script_relay_sends_both_versions(settings, monkeypatch):
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.Client
    monkeypatch.setattr(mailer.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    s = _relay_settings(settings)
    msg = mailer.build_message(s, "x@usc.edu", "Hello", "plain body", "<p>html body</p>")
    mailer.get_backend(s).send(msg)
    assert sent["key"] == "relay-key"
    assert sent["to"] == "x@usc.edu"
    assert sent["subject"] == "Hello"
    assert sent["text"].strip() == "plain body"
    assert sent["html"].strip() == "<p>html body</p>"
    assert sent["name"] == "Tro"


def test_apps_script_relay_reports_refusals(settings, monkeypatch):
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": False, "error": "bad key"}))
    monkeypatch.setattr(mailer.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    s = _relay_settings(settings)
    with pytest.raises(mailer.EmailError, match="bad key"):
        mailer.get_backend(s).send(mailer.build_message(s, "x@usc.edu", "Hi", "t", "<p>h</p>"))


def test_apps_script_relay_needs_its_settings(settings):
    with pytest.raises(mailer.EmailError):
        mailer.get_backend(dataclasses.replace(settings, email_backend="apps_script"))

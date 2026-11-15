"""Small pure functions."""

from __future__ import annotations

import pytest

from app import storage
from app.bracelets import normalize_bracelet_id
from app.security import issue_token, read_token
from conftest import JPEG_BYTES, PNG_BYTES


@pytest.mark.parametrize(
    "raw,expected",
    [("a4:cf:12:9b:00:1e", "A4CF129B001E"), ("A4-CF-12", "A4CF12"), (" ab01 ", "AB01"), ("node_7", "NODE_7")],
)
def test_normalize_bracelet_id(raw, expected):
    assert normalize_bracelet_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "::", "a/b", "x" * 65, "<script>"])
def test_normalize_bracelet_id_rejects(raw):
    with pytest.raises(ValueError):
        normalize_bracelet_id(raw)


def test_image_extension_by_magic_bytes():
    assert storage.image_extension(JPEG_BYTES) == ".jpg"
    assert storage.image_extension(PNG_BYTES) == ".png"
    assert storage.image_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert storage.image_extension(b"RIFF\x00\x00\x00\x00WAVEfmt ") is None
    assert storage.image_extension(b"") is None


def test_resolve_media_stays_inside(tmp_path):
    assert storage.resolve_media(tmp_path, "photos/a.jpg") == (tmp_path / "photos/a.jpg").resolve()
    assert storage.resolve_media(tmp_path, "../outside.txt") is None
    assert storage.resolve_media(tmp_path, "/etc/passwd") is None


def test_safe_filename():
    assert storage.safe_filename("../../etc/passwd", "f") == "passwd"
    assert storage.safe_filename("my talk (1).wav", "f") == "mytalk1.wav"
    assert storage.safe_filename(".hidden", "f") == "hidden"
    assert storage.safe_filename(None, "fallback") == "fallback"


def test_tokens_round_trip_and_reject_tampering(settings):
    token = issue_token(settings, 42)
    assert read_token(settings, token) == 42
    assert read_token(settings, token + "x") is None
    other = type(settings)(**{**settings.__dict__, "secret_key": "different"})
    assert read_token(other, token) is None


def test_tokens_expire(settings):
    import dataclasses

    expired = dataclasses.replace(settings, token_max_age=-1)
    assert read_token(expired, issue_token(settings, 1)) is None


def test_old_database_gets_new_columns(tmp_path):
    """A tro.db from an older version (missing columns) keeps working."""
    import sqlite3

    from sqlmodel import Session, select

    from app.db import make_engine
    from app.models import Preferences, User

    path = tmp_path / "old.db"
    engine = make_engine(f"sqlite:///{path}")
    engine.dispose()
    con = sqlite3.connect(path)
    con.execute('ALTER TABLE "user" DROP COLUMN position')
    con.execute("ALTER TABLE preferences DROP COLUMN recommendations_opt_in")
    con.execute("ALTER TABLE connection DROP COLUMN recorded")
    con.execute("INSERT INTO user (name, interests, created_at, updated_at) VALUES ('Old', '[]', '2026-01-01', '2026-01-01')")
    con.commit()
    con.close()

    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        user = s.exec(select(User)).one()
        assert user.position is None
        s.exec(select(Preferences)).all()
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(connection)")]
    assert "recorded" in cols

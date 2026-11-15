"""Pairing the Apple Watch app with a one-time code, then recording from it."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from app.models import WatchPairing
from test_phone_mic import _phone, fake_ai, pair  # noqa: F401  (fixtures)
from test_recordings import two_clips


def _code(client, event_id, headers):
    resp = client.post(f"/events/{event_id}/watch-code", headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["code"]


def test_watch_pairs_with_a_code_and_records(client, pair, fake_ai, db):  # noqa: F811
    code = _code(client, pair["event"], pair["alice_h"])
    assert len(code) == 6 and code.isdigit()
    stored = db.exec(select(WatchPairing)).one()
    assert code not in stored.code_hash  # only a hash is kept

    resp = client.post("/auth/watch", json={"code": code})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_id"] == pair["event"] and body["first_name"] == "Alice"
    watch = {"Authorization": f"Bearer {body['token']}"}
    # The watch is signed in as Alice: it can see her taps and upload a conversation.
    cards = client.get(f"/events/{pair['event']}/connections", headers=watch).json()
    assert cards[0]["connection_id"] == pair["conn"]
    assert _phone(client, pair["event"], watch, two_clips()[0], connection_id=pair["conn"]).status_code == 201

    # A code works once.
    assert client.post("/auth/watch", json={"code": code}).status_code == 401


def test_codes_expire_and_new_ones_cancel_old_ones(client, pair, db):  # noqa: F811
    first = _code(client, pair["event"], pair["alice_h"])
    second = _code(client, pair["event"], pair["alice_h"])
    assert first == second or client.post("/auth/watch", json={"code": first}).status_code == 401
    row = db.exec(select(WatchPairing)).one()
    row.expires_at = row.expires_at - timedelta(minutes=10)
    db.add(row)
    db.commit()
    assert client.post("/auth/watch", json={"code": second}).status_code == 401


def test_pairing_needs_sign_in_a_bracelet_and_a_real_code(client, pair, make_user):  # noqa: F811
    assert client.post(f"/events/{pair['event']}/watch-code").status_code == 401
    _, no_bracelet = make_user(name="Cara Wu")
    assert client.post(f"/events/{pair['event']}/watch-code", headers=no_bracelet).status_code == 409
    for bad in ("12345", "abcdef", "1234567"):
        assert client.post("/auth/watch", json={"code": bad}).status_code == 422


def test_guessing_codes_is_rate_limited(client, pair):  # noqa: F811
    codes = [client.post("/auth/watch", json={"code": f"{i:06d}"}).status_code for i in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429

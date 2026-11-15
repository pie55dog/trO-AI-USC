"""Signing the trO Apple Watch app in with a 6-digit code (see watch/README.md).

    POST /events/{id}/watch-code   (attendee, on the phone) get a code for this event
    POST /auth/watch               (the watch) trade the code for a login token

Typing an email and password on a watch is miserable, and a QR scanner
doesn't exist there, so the phone (already signed in) shows a code and the
watch types 6 digits. Codes:

  * live 5 minutes and work once; asking for a new one cancels older ones;
  * are stored only as an HMAC (keyed with SECRET_KEY), never in plain text;
  * are rate-limited per network address on the watch side (10 tries a
    minute), so guessing one of a million codes in 5 minutes is hopeless.

The token the watch gets is a normal login token: "sign out everywhere"
(session_version) and deleting the account revoke it like any other.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..config import Settings
from ..db import get_session
from ..models import BraceletAssignment, Event, User, WatchPairing, utcnow
from ..ratelimit import WATCH_CODE_TRIES, WATCH_CODES_ISSUED, client_ip
from ..security import current_user, get_settings, issue_token

router = APIRouter(tags=["watch"])
DB = Annotated[Session, Depends(get_session)]

CODE_TTL = timedelta(minutes=5)


class WatchCodeOut(BaseModel):
    code: str
    expires_at: datetime


class WatchPairIn(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class WatchPairOut(BaseModel):
    token: str
    event_id: int
    event_name: str
    first_name: str


def _hash(settings: Settings, code: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"watch:{code}".encode(), hashlib.sha256).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("/events/{event_id}/watch-code", response_model=WatchCodeOut, status_code=status.HTTP_201_CREATED)
def make_watch_code(
    event_id: int,
    user: Annotated[User, Depends(current_user)],
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
) -> WatchCodeOut:
    """A one-time code to type on the watch. Needs a bracelet linked at this event."""
    WATCH_CODES_ISSUED.check(f"user:{user.id}")
    if session.get(Event, event_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    linked = session.exec(
        select(BraceletAssignment).where(BraceletAssignment.event_id == event_id, BraceletAssignment.user_id == user.id)
    ).first()
    if linked is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "link your bracelet for this event first")
    # One live code per person: a new one cancels the old.
    for old in session.exec(select(WatchPairing).where(WatchPairing.user_id == user.id, WatchPairing.used_at == None)).all():  # noqa: E711
        session.delete(old)
    now = utcnow()
    for _ in range(5):
        code = f"{secrets.randbelow(1_000_000):06d}"
        if not session.exec(select(WatchPairing).where(WatchPairing.code_hash == _hash(settings, code))).first():
            break
    pairing = WatchPairing(code_hash=_hash(settings, code), user_id=user.id, event_id=event_id, expires_at=now + CODE_TTL)
    session.add(pairing)
    session.commit()
    return WatchCodeOut(code=code, expires_at=pairing.expires_at)


@router.post("/auth/watch", response_model=WatchPairOut)
def pair_watch(
    body: WatchPairIn,
    request: Request,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
) -> WatchPairOut:
    """Trade a code from the phone for a login token. 401 for any wrong, used or expired code."""
    WATCH_CODE_TRIES.check(f"ip:{client_ip(request)}")
    pairing = session.exec(select(WatchPairing).where(WatchPairing.code_hash == _hash(settings, body.code))).first()
    now = utcnow()
    # Same answer for every failure, so a guesser learns nothing.
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "that code didn't work: get a new one on your phone")
    if pairing is None or pairing.used_at is not None or _aware(pairing.expires_at) < now:
        raise invalid
    user = session.get(User, pairing.user_id)
    event = session.get(Event, pairing.event_id)
    if user is None or event is None:
        raise invalid
    pairing.used_at = now
    session.add(pairing)
    session.commit()
    first = user.name.split()[0] if user.name.strip() else "there"
    return WatchPairOut(
        token=issue_token(settings, user.id, user.session_version), event_id=event.id, event_name=event.name, first_name=first
    )

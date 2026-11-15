"""Events, bracelet assignment, and the post-event email trigger.

    POST /events                          (organizer) create an event
    GET  /events                          list events
    GET  /events/{id}                     one event
    POST /events/{id}/bracelet            (attendee) claim a bracelet for this event
    GET  /events/{id}/bracelet            (attendee) which bracelet I have
    GET  /events/{id}/connections         (attendee) who I tapped at this event
    POST /events/{id}/send-summaries      (organizer) email every attendee

"Organizer" endpoints need the X-Admin-Key header.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, or_, select

from .. import mailer, post_event
from ..config import Settings
from ..db import get_session
from ..models import SHAREABLE_FIELDS, BraceletAssignment, Connection, Event, Preferences, User, utcnow
from ..schemas import (
    BraceletAssignmentOut,
    BraceletClaim,
    ConnectionOut,
    EventCreate,
    EventOut,
    SendSummariesRequest,
    SendSummariesResult,
)
from ..security import current_user, get_settings, require_admin
from .users import onboarding_status, photo_url

router = APIRouter(prefix="/events", tags=["events"])

DB = Annotated[Session, Depends(get_session)]


def _event_or_404(session: Session, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


def _event_out(e: Event) -> EventOut:
    return EventOut(id=e.id, name=e.name, location=e.location, starts_at=e.starts_at)


@router.post("", response_model=EventOut, status_code=201, dependencies=[Depends(require_admin)])
def create_event(body: EventCreate, session: DB) -> EventOut:
    event = Event(**body.model_dump())
    session.add(event)
    session.commit()
    session.refresh(event)
    return _event_out(event)


@router.get("", response_model=list[EventOut])
def list_events(session: DB) -> list[EventOut]:
    return [_event_out(e) for e in session.exec(select(Event).order_by(Event.id.desc())).all()]


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, session: DB) -> EventOut:
    return _event_out(_event_or_404(session, event_id))


@router.post("/{event_id}/bracelet", response_model=BraceletAssignmentOut)
def claim_bracelet(
    event_id: int,
    body: BraceletClaim,
    user: Annotated[User, Depends(current_user)],
    session: DB,
) -> BraceletAssignmentOut:
    """Tie a bracelet (by its ESP32 id) to the signed-in attendee.

    Onboarding must be finished first, because the bracelet's behavior
    depends on the recording-consent answer.

    Claiming again with a different id swaps bracelets (e.g. a dead battery
    at check-in). A bracelet already held by someone else at this event is
    refused.
    """
    _event_or_404(session, event_id)

    status_ = onboarding_status(user, session.get(Preferences, user.id))
    if not status_.complete:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "finish onboarding before claiming a bracelet", "missing": status_.missing},
        )

    holder = session.exec(
        select(BraceletAssignment).where(
            BraceletAssignment.event_id == event_id, BraceletAssignment.bracelet_id == body.bracelet_id
        )
    ).first()
    if holder is not None and holder.user_id != user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "this bracelet is already assigned to someone else")

    mine = session.exec(
        select(BraceletAssignment).where(
            BraceletAssignment.event_id == event_id, BraceletAssignment.user_id == user.id
        )
    ).first()
    if mine is None:
        mine = BraceletAssignment(event_id=event_id, user_id=user.id, bracelet_id=body.bracelet_id)
    elif mine.bracelet_id != body.bracelet_id:
        mine.bracelet_id = body.bracelet_id
        mine.assigned_at = utcnow()
    session.add(mine)
    try:
        session.commit()
    except IntegrityError:
        # Someone else grabbed the same bracelet between our check and commit.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "this bracelet is already assigned to someone else") from None
    session.refresh(mine)
    return BraceletAssignmentOut(event_id=mine.event_id, bracelet_id=mine.bracelet_id, assigned_at=mine.assigned_at)


@router.get("/{event_id}/bracelet", response_model=BraceletAssignmentOut)
def my_bracelet(
    event_id: int,
    user: Annotated[User, Depends(current_user)],
    session: DB,
) -> BraceletAssignmentOut:
    mine = session.exec(
        select(BraceletAssignment).where(
            BraceletAssignment.event_id == event_id, BraceletAssignment.user_id == user.id
        )
    ).first()
    if mine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no bracelet assigned for this event")
    return BraceletAssignmentOut(event_id=mine.event_id, bracelet_id=mine.bracelet_id, assigned_at=mine.assigned_at)


@router.get("/{event_id}/connections", response_model=list[ConnectionOut])
def my_connections(
    event_id: int,
    user: Annotated[User, Depends(current_user)],
    session: DB,
) -> list[ConnectionOut]:
    """Everyone the signed-in user tapped at this event, newest first.

    Empty until bracelet processing creates connections. Contact info is
    limited to what each person chose to share.
    """
    _event_or_404(session, event_id)
    rows = session.exec(
        select(Connection)
        .where(Connection.event_id == event_id)
        .where(or_(Connection.user_a_id == user.id, Connection.user_b_id == user.id))
        .order_by(Connection.tapped_at.desc())
    ).all()
    my_prefs = session.get(Preferences, user.id)
    out = []
    for row in rows:
        other_id = row.user_b_id if row.user_a_id == user.id else row.user_a_id
        other = session.get(User, other_id)
        if other is None:
            continue
        prefs = session.get(Preferences, other_id)
        shared = prefs.shared_fields if prefs else []
        contact = {f: getattr(other, f) for f in SHAREABLE_FIELDS if f in shared and getattr(other, f)}
        recorded = bool(my_prefs and my_prefs.recording_consent and prefs and prefs.recording_consent)
        out.append(
            ConnectionOut(
                user_id=other.id,
                name=other.name,
                position=other.position,
                school=other.school,
                major=other.major,
                bio=other.bio,
                photo_url=photo_url(other),
                recorded=recorded,
                contact=contact,
                tapped_at=row.tapped_at,
            )
        )
    return out


@router.post(
    "/{event_id}/send-summaries",
    response_model=SendSummariesResult,
    dependencies=[Depends(require_admin)],
)
def send_summaries(
    event_id: int,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    body: SendSummariesRequest | None = None,
) -> SendSummariesResult:
    """Email every attendee who they met. Safe to re-run: already-sent emails are skipped.

    Runs synchronously, which is fine for a few hundred attendees. For a big
    career fair, move this to a background job.
    """
    event = _event_or_404(session, event_id)
    try:
        report = post_event.send_event_emails(session, settings, event, resend=bool(body and body.resend))
    except mailer.EmailError as exc:  # e.g. SMTP not configured
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return SendSummariesResult(**report.__dict__)

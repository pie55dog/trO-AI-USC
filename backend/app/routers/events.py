"""Events, bracelet assignment, and the post-event email trigger.

    POST /events                          (organizer) create an event
    GET  /events                          list events
    GET  /events/{id}                     one event
    POST /events/{id}/bracelet            (attendee) claim a bracelet for this event
    GET  /events/{id}/bracelet            (attendee) which bracelet I have
    GET  /events/{id}/connections         (attendee) who I tapped at this event
    POST /events/{id}/send-summaries      (organizer) email every attendee
    POST /events/{id}/test-email          (attendee) email me my summary now

"Organizer" endpoints need the X-Admin-Key header.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import mailer, post_event
from ..config import Settings
from ..db import get_session
from ..connections import connected_people, shared_contact
from ..models import BraceletAssignment, Event, Preferences, User, utcnow
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

    Connections appear the moment two bracelets pair (POST /bracelets/tap).
    Contact info is limited to what each person chose to share.
    """
    _event_or_404(session, event_id)
    return [
        ConnectionOut(
            user_id=c.person.id,
            name=c.person.name,
            position=c.person.position,
            school=c.person.school,
            major=c.person.major,
            bio=c.person.bio,
            photo_url=photo_url(c.person),
            recorded=c.connection.recorded,
            starred=c.starred,
            contact=shared_contact(c.person, c.prefs),
            tapped_at=c.connection.tapped_at,
        )
        for c in connected_people(session, event_id, user.id, newest_first=True)
    ]


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


@router.post("/{event_id}/test-email")
def send_my_test_email(
    event_id: int,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, str | bool]:
    """Email the signed-in person their summary for this event right now.

    Only ever goes to their own address. Doesn't count as the post-event email.
    ``delivered`` is false when the server only saves emails to its outbox
    folder (EMAIL_BACKEND=console), so the app doesn't say "check your inbox".
    """
    event = _event_or_404(session, event_id)
    try:
        sent_to = post_event.send_test_email(session, settings, event, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except mailer.EmailError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"sent_to": sent_to, "delivered": settings.email_backend == "smtp"}

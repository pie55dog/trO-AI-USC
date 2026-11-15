"""Organizer console endpoints (header X-Admin-Key).

    PATCH  /events/{id}                       edit name, location, start time
    GET    /events/{id}/overview              registration and email counts
    GET    /events/{id}/attendees             everyone holding a bracelet
    POST   /events/{id}/attendees             check-in desk: link a bracelet to an attendee by email
    DELETE /events/{id}/attendees/{user_id}   take a bracelet back (returned, lost, swapped)

Creating events and sending summaries live in events.py.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, or_, select

from ..db import get_session
from ..models import BraceletAssignment, BraceletUpload, Connection, EmailLog, Event, Preferences, User, utcnow
from ..schemas import AttendeeOut, DeskAssign, EventOut, EventOverview, EventUpdate
from ..security import require_admin
from .users import onboarding_status, photo_url

router = APIRouter(prefix="/events", tags=["organizer"], dependencies=[Depends(require_admin)])

DB = Annotated[Session, Depends(get_session)]


def _event_or_404(session: Session, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


def _event_out(e: Event) -> EventOut:
    return EventOut(id=e.id, name=e.name, location=e.location, starts_at=e.starts_at)


def _assignments(session: Session, event_id: int) -> list[BraceletAssignment]:
    return list(
        session.exec(
            select(BraceletAssignment)
            .where(BraceletAssignment.event_id == event_id)
            .order_by(col(BraceletAssignment.assigned_at).desc())
        ).all()
    )


@router.patch("/{event_id}", response_model=EventOut)
def update_event(event_id: int, body: EventUpdate, session: DB) -> EventOut:
    event = _event_or_404(session, event_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and not changes["name"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "name can't be empty")
    for key, value in changes.items():
        setattr(event, key, value)
    session.add(event)
    session.commit()
    session.refresh(event)
    return _event_out(event)


@router.get("/{event_id}/overview", response_model=EventOverview)
def event_overview(event_id: int, session: DB) -> EventOverview:
    event = _event_or_404(session, event_id)
    user_ids = [a.user_id for a in _assignments(session, event_id)]
    prefs = (
        session.exec(select(Preferences).where(col(Preferences.user_id).in_(user_ids))).all() if user_ids else []
    )

    def count(stmt) -> int:
        return int(session.exec(stmt).one() or 0)

    return EventOverview(
        event=_event_out(event),
        attendees=len(user_ids),
        recording_consent=sum(1 for p in prefs if p.recording_consent),
        summary_email_opt_in=sum(1 for p in prefs if p.summary_email_opt_in),
        connections=count(select(func.count()).select_from(Connection).where(Connection.event_id == event_id)),
        uploads_received=count(
            select(func.count()).select_from(BraceletUpload).where(BraceletUpload.event_id == event_id)
        ),
        emails_sent=count(
            select(func.count()).select_from(EmailLog).where(EmailLog.event_id == event_id, EmailLog.status == "sent")
        ),
        emails_failed=count(
            select(func.count())
            .select_from(EmailLog)
            .where(EmailLog.event_id == event_id, EmailLog.status == "failed")
        ),
    )


@router.get("/{event_id}/attendees", response_model=list[AttendeeOut])
def list_attendees(event_id: int, session: DB) -> list[AttendeeOut]:
    """Everyone holding a bracelet for this event, most recent check-in first."""
    _event_or_404(session, event_id)
    assignments = _assignments(session, event_id)
    ids = [a.user_id for a in assignments]
    if not ids:
        return []
    users = {u.id: u for u in session.exec(select(User).where(col(User.id).in_(ids))).all()}
    prefs = {p.user_id: p for p in session.exec(select(Preferences).where(col(Preferences.user_id).in_(ids))).all()}
    emails = {
        e.user_id: e.status
        for e in session.exec(select(EmailLog).where(EmailLog.event_id == event_id)).all()
    }
    taps: dict[int, int] = {}
    for c in session.exec(
        select(Connection).where(
            Connection.event_id == event_id,
            or_(col(Connection.user_a_id).in_(ids), col(Connection.user_b_id).in_(ids)),
        )
    ).all():
        taps[c.user_a_id] = taps.get(c.user_a_id, 0) + 1
        taps[c.user_b_id] = taps.get(c.user_b_id, 0) + 1

    out = []
    for a in assignments:
        user = users.get(a.user_id)
        if user is None:
            continue
        p = prefs.get(a.user_id)
        out.append(
            AttendeeOut(
                user_id=user.id,
                name=user.name,
                email=user.email,
                school=user.school,
                major=user.major,
                photo_url=photo_url(user),
                bracelet_id=a.bracelet_id,
                assigned_at=a.assigned_at,
                recording_consent=p.recording_consent if p else None,
                summary_email_opt_in=p.summary_email_opt_in if p else True,
                connections=taps.get(user.id, 0),
                email_status=emails.get(user.id),
            )
        )
    return out


@router.post("/{event_id}/attendees", response_model=AttendeeOut, status_code=201)
def desk_assign(event_id: int, body: DeskAssign, session: DB) -> AttendeeOut:
    """Link a bracelet to someone who already set up their trO profile.

    Same rules as an attendee claiming their own bracelet: the profile and
    both consent answers must be done, and a bracelet held by someone else
    at this event is refused. Assigning again to the same person swaps
    their bracelet.
    """
    _event_or_404(session, event_id)
    user = session.exec(select(User).where(User.email == body.email)).first()
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no trO account uses that email. Ask them to open the event link and set up their profile first",
        )
    status_ = onboarding_status(user, session.get(Preferences, user.id))
    if not status_.complete:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "they haven't finished setting up their profile yet", "missing": status_.missing},
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
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "this bracelet is already assigned to someone else") from None

    return next(a for a in list_attendees(event_id, session) if a.user_id == user.id)


@router.delete("/{event_id}/attendees/{user_id}", status_code=204)
def release_bracelet(event_id: int, user_id: int, session: DB) -> Response:
    """Take a bracelet back so it can be handed to someone else.

    Their connections and any uploads stay; they just stop being an
    attendee until they claim a bracelet again.
    """
    _event_or_404(session, event_id)
    mine = session.exec(
        select(BraceletAssignment).where(
            BraceletAssignment.event_id == event_id, BraceletAssignment.user_id == user_id
        )
    ).first()
    if mine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "that person has no bracelet for this event")
    session.delete(mine)
    session.commit()
    return Response(status_code=204)

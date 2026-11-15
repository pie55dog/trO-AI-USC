"""Events, bracelet assignment, and the post-event email trigger.

    POST /events                          (organizer) create an event
    GET  /events                          list events
    GET  /events/{id}                     one event
    POST /events/{id}/bracelet            (attendee) claim a bracelet for this event
    GET  /events/{id}/bracelet            (attendee) which bracelet I have
    GET  /events/{id}/connections         (attendee) who I tapped at this event
    POST /events/{id}/recordings          (attendee) a clip from the phone mic (until bracelets have mics)
    POST /events/{id}/send-summaries      (organizer) email every attendee
    POST /events/{id}/test-email          (attendee) email me my summary now

"Organizer" endpoints need the X-Admin-Key header.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import mailer, notes, post_event, recordings, speakers
from ..ratelimit import PHONE_UPLOADS, TEST_EMAILS
from ..config import Settings
from ..db import get_session
from ..connections import shared_contact
from ..models import BraceletAssignment, Connection, Event, Preferences, Recording, User, utcnow
from ..schemas import (
    BraceletAssignmentOut,
    BraceletClaim,
    ConnectionOut,
    EventCreate,
    EventOut,
    NotesPreview,
    RecordingOut,
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
    mine = session.get(Preferences, user.id)
    i_consent = bool(mine and mine.recording_consent)
    return [
        connection_out(p, i_consent=i_consent)
        for p in notes.event_notes(session, event_id, user.id, newest_first=True).people
    ]


def connection_out(p: notes.PersonNotes, *, i_consent: bool = False) -> ConnectionOut:
    c = p.who
    return ConnectionOut(
        user_id=c.person.id,
        connection_id=c.connection.id,
        both_consented=i_consent and bool(c.prefs and c.prefs.recording_consent),
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
        notes=NotesPreview(
            conversation=p.conversation_status,
            voice_notes=len(p.voice_notes),
            follow_ups=len(p.follow_ups),
        ),
    )


PHONE_MIC = "PHONE"  # bracelet_id stored on clips that came from the phone mic
# The phone stops at 3 minutes / 30 seconds (frontend phoneMic/controller.ts); allow a little slack.
PHONE_MAX_SECONDS = {"conversation": 200, "voice_note": 40}
# A pair who tap again reuses their connection; more clips than this is a loop or abuse.
PHONE_MAX_CLIPS_PER_CONNECTION = 3


def _save_phone_clip(
    session: Session,
    settings: Settings,
    user_id: int,
    event_id: int,
    kind: str,
    connection_id: Optional[int],
    started_at: Optional[int],
    data: bytes,
    content_type: str,
) -> RecordingOut:
    _event_or_404(session, event_id)
    if kind not in recordings.KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "kind must be conversation or voice_note")
    conn = None
    if kind == "conversation":
        if connection_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "connection_id is required for a conversation")
        conn = session.get(Connection, connection_id)
        if conn is None or conn.event_id != event_id or user_id not in (conn.user_a_id, conn.user_b_id):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "that connection isn't yours")
    assignment = session.exec(
        select(BraceletAssignment).where(BraceletAssignment.event_id == event_id, BraceletAssignment.user_id == user_id)
    ).first()
    if assignment is None and conn is None:
        # A conversation proves they're at the event; a voice note needs a linked bracelet.
        raise HTTPException(status.HTTP_409_CONFLICT, "link your bracelet for this event first")
    if conn is not None:
        sent = session.exec(
            select(Recording.id).where(Recording.connection_id == conn.id, Recording.user_id == user_id)
        ).all()
        if len(sent) >= PHONE_MAX_CLIPS_PER_CONNECTION:
            raise HTTPException(status.HTTP_409_CONFLICT, "this conversation already has its recordings")
    # The phone always sends 16 kHz WAV. Anything else (or anything longer than the
    # phone ever records) is refused before it costs a transcription.
    if data:
        try:
            samples, rate = speakers.decode_wav(data)
        except ValueError:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "phone clips must be WAV audio") from None
        if not rate or len(samples) / rate > PHONE_MAX_SECONDS[kind]:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"{kind.replace('_', ' ')} is too long")
        content_type = "audio/wav"
    started = None
    if started_at and started_at > 1_600_000_000_000:  # Unix ms from the phone's clock
        started = datetime.fromtimestamp(started_at / 1000, tz=timezone.utc)
    try:
        rec = recordings.save_recording(
            session,
            settings,
            kind=kind,
            event_id=event_id,
            user_id=user_id,
            bracelet_id=PHONE_MIC,
            data=data,
            content_type=content_type,
            connection=conn,
            started_at=started,
        )
    except recordings.ConsentError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return RecordingOut(id=rec.id, kind=rec.kind, status=rec.status, connection_id=rec.connection_id, duration_s=rec.duration_s)


@router.post("/{event_id}/recordings", response_model=RecordingOut, status_code=status.HTTP_201_CREATED)
async def upload_phone_recording(
    event_id: int,
    request: Request,
    background: BackgroundTasks,
    user: Annotated[User, Depends(current_user)],
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    kind: Annotated[str, Query()],
    connection_id: Annotated[Optional[int], Query()] = None,
    started_at: Annotated[Optional[int], Query(description="Unix ms from the phone's clock")] = None,
) -> RecordingOut:
    """One clip from the phone mic, sent by the signed-in attendee (raw WAV body).

    Stand-in for the bracelet mic: the bracelet still does the tap, and the
    phone in the wearer's pocket or hand records. Same rules and pipeline as
    POST /bracelets/recordings (consent checked again here, 403 if either
    person said no; 413 over 24 MB), just authenticated as the person
    instead of with the bracelet key. Rate-limited per person, WAV only.
    """
    PHONE_UPLOADS.check(f"user:{user.id}")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > recordings.MAX_RECORDING_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "recordings must be under 24 MB")
    content_type = (request.headers.get("content-type") or "audio/wav").split(";")[0].strip()
    out = await run_in_threadpool(
        _save_phone_clip, session, settings, user.id, event_id, kind, connection_id, started_at, bytes(body), content_type
    )
    app = request.app
    background.add_task(recordings.run_in_background, app.state.engine, settings, app.state.ai_factory, out.id)
    return out


@router.post(
    "/{event_id}/send-summaries",
    response_model=SendSummariesResult,
    dependencies=[Depends(require_admin)],
)
def send_summaries(
    event_id: int,
    request: Request,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    body: SendSummariesRequest | None = None,
) -> SendSummariesResult:
    """Email every attendee who they met. Safe to re-run: already-sent emails are skipped.

    Unprocessed recordings are finished first. Once every email has gone
    out, the event's audio, transcripts and loudness data are deleted.

    Runs synchronously, which is fine for a few hundred attendees. For a big
    career fair, move this to a background job.
    """
    event = _event_or_404(session, event_id)
    # Finish any conversations or voice notes still waiting, so they make the email.
    recordings.process_pending(session, settings, request.app.state.ai_factory, event_id)
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
    TEST_EMAILS.check(f"user:{user.id}")
    try:
        sent_to = post_event.send_test_email(session, settings, event, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except mailer.EmailError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"sent_to": sent_to, "delivered": settings.email_backend == "smtp"}

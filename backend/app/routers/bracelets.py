"""Endpoints the bracelets call (all need the X-Bracelet-Key header).

    GET  /bracelets/{id}/status   has anyone claimed this bracelet yet? (polled at boot)
    POST /bracelets/tap           live tap: "I'm touching that bracelet" (see app/taps.py)
    POST /bracelets/star          star the wearer's latest connection (button click)
    POST /bracelets/recordings    one audio clip: a conversation or a voice note (mic build)
    POST /bracelets/uploads       end-of-event upload (store only, anything else)

Recording upload (the mic build, see firmware/README.md):

    POST /bracelets/recordings?device=TRO-1A2B3C&kind=conversation&connection_id=42&started_at=1763190000123
    Content-Type: audio/wav
    <body: the WAV file, 16 kHz 16-bit mono>

    kind           "conversation" (needs connection_id: the "session" from the
                   tap response) or "voice_note"
    started_at     optional, Unix time in ms from the bracelet's clock (NTP);
                   lines up the two bracelets' clips of one conversation
    -> 201 {"id": 7, "status": "received"}
       403 one of the two people hasn't agreed to recording (audio discarded)
       409 bracelet not linked;  413 over 24 MB;  422 bad parameters

The audio is transcribed and turned into notes in the background (see
app/recordings.py).

Upload details:

At the end of an event each bracelet (or the phone hotspot relaying for it)
sends what it collected. The exact format belongs to the hardware team, so
this endpoint is deliberately loose. It accepts a multipart form with:

    bracelet_id   required, the ESP32's id
    event_id      optional, but required once a bracelet has been used at more
                  than one event (we won't guess whose data it is)
    payload       optional JSON text (tap log, timestamps, anything)
    files         optional, zero or more files (conversation audio, voice notes)

Everything is saved untouched with status "received". Nothing is parsed,
transcribed or summarized yet; see ``bracelets.process_upload``.
"""

from __future__ import annotations

import json
from typing import Annotated, Optional

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, select

from .. import recordings, storage, taps
from ..bracelets import normalize_bracelet_id
from ..ratelimit import BRACELET_UPLOADS
from ..config import Settings
from ..db import get_session
from ..models import BraceletAssignment, BraceletUpload, Connection, Event, Preferences, User
from ..schemas import BraceletStatusOut, BraceletUploadOut, RecordingOut, StarIn, StarOut, TapIn, TapOut
from ..security import get_settings, require_bracelet

router = APIRouter(prefix="/bracelets", tags=["bracelets"], dependencies=[Depends(require_bracelet)])

MAX_FILE_BYTES = 100 * 1024 * 1024  # ~100 MB per file is far beyond a night of compressed audio
MAX_FILES = 200
_CHUNK = 1024 * 1024

NOT_LINKED = "this bracelet isn't linked to anyone yet: tap a phone to it and sign up"


@router.get("/{bracelet_id}/status", response_model=BraceletStatusOut)
def bracelet_status(bracelet_id: str, session: Annotated[Session, Depends(get_session)]) -> BraceletStatusOut:
    """Whether someone has claimed this bracelet. The bracelet polls this until they have."""
    try:
        bid = normalize_bracelet_id(bracelet_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    assignment = taps.current_assignment(session, bid)
    if assignment is None:
        return BraceletStatusOut(bracelet_id=bid, linked=False)
    user = session.get(User, assignment.user_id)
    prefs = session.get(Preferences, assignment.user_id)
    return BraceletStatusOut(
        bracelet_id=bid,
        linked=True,
        event_id=assignment.event_id,
        first_name=(user.name.split()[0] if user and user.name.strip() else None),
        recording_consent=prefs.recording_consent if prefs else None,
    )


# Plain ``def`` endpoints run in FastAPI's thread pool, so a burst of tap
# retries from many bracelets doesn't block the event loop.
@router.post("/tap", response_model=TapOut)
def tap(body: TapIn, session: Annotated[Session, Depends(get_session)]) -> TapOut:
    """Report a tap. Answers "waiting" until the other bracelet reports it too, then "paired".

    409 means this bracelet isn't linked to anyone yet.
    """
    try:
        result = taps.report_tap(session, body.device, body.peer, rssi=body.rssi, event_id=body.event_id)
    except taps.NotLinked:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_LINKED) from None
    if result.status != "paired" or result.connection is None:
        return TapOut(status="waiting")
    return TapOut(
        status="paired",
        session=str(result.connection.id),
        connection_id=result.connection.id,
        peer_name=result.peer.name if result.peer else None,
        match_pct=result.match_pct,
        both_consented=result.both_consented,
    )


@router.post("/star", response_model=StarOut)
def star(body: StarIn, session: Annotated[Session, Depends(get_session)]) -> StarOut:
    """Star the wearer's most recent connection (shows on their dashboard and in the email)."""
    try:
        found = taps.star_latest(session, body.device, body.event_id)
    except taps.NotLinked:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_LINKED) from None
    if found is None:
        return StarOut(status="no_connection")
    conn, other = found
    return StarOut(status="starred", connection_id=conn.id, peer_name=other.name if other else None)


def _save_clip(
    session: Session,
    settings: Settings,
    device: str,
    kind: str,
    connection_id: Optional[int],
    started_at: Optional[int],
    event_id: Optional[int],
    data: bytes,
    content_type: str,
) -> RecordingOut:
    try:
        bid = normalize_bracelet_id(device)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if kind not in recordings.KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "kind must be conversation or voice_note")
    assignment = taps.current_assignment(session, bid, event_id)
    if assignment is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_LINKED)

    conn = None
    if kind == "conversation":
        if connection_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "connection_id is required for a conversation")
        conn = session.get(Connection, connection_id)
        if (
            conn is None
            or conn.event_id != assignment.event_id
            or assignment.user_id not in (conn.user_a_id, conn.user_b_id)
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "that connection isn't this wearer's")

    started = None
    if started_at:
        # Ignore a clock that is obviously unset (an ESP32 without NTP starts at 1970).
        if started_at > 1_600_000_000_000:
            started = datetime.fromtimestamp(started_at / 1000, tz=timezone.utc)
    try:
        rec = recordings.save_recording(
            session,
            settings,
            kind=kind,
            event_id=assignment.event_id,
            user_id=assignment.user_id,
            bracelet_id=bid,
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


@router.post("/recordings", response_model=RecordingOut, status_code=status.HTTP_201_CREATED)
async def upload_recording(
    request: Request,
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    device: Annotated[str, Query(max_length=64)],
    kind: Annotated[str, Query()],
    connection_id: Annotated[Optional[int], Query()] = None,
    started_at: Annotated[Optional[int], Query(description="Unix ms from the bracelet's clock")] = None,
    event_id: Annotated[Optional[int], Query()] = None,
) -> RecordingOut:
    """One audio clip from a bracelet, sent as the raw request body.

    Raw bytes (not a multipart form) because that's simplest to send from an
    ESP32 straight out of its memory. Transcription and notes happen after
    the response, so the bracelet isn't kept waiting.
    """
    # Each clip costs an AI call: cap it per bracelet. (Not per address: every
    # bracelet at an event shares one phone hotspot.)
    BRACELET_UPLOADS.check(f"device:{device.upper()}")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > recordings.MAX_RECORDING_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "recordings must be under 24 MB")
    content_type = (request.headers.get("content-type") or "audio/wav").split(";")[0].strip()
    out = await run_in_threadpool(
        _save_clip, session, settings, device, kind, connection_id, started_at, event_id, bytes(body), content_type
    )
    app = request.app
    background.add_task(recordings.run_in_background, app.state.engine, settings, app.state.ai_factory, out.id)
    return out


# A plain ``def`` (not async) so FastAPI runs it in a worker thread: the
# disk writes and database calls below would otherwise block every other
# request while a large upload is saved.
@router.post("/uploads", response_model=BraceletUploadOut, status_code=status.HTTP_201_CREATED)
def receive_upload(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    bracelet_id: Annotated[str, Form()],
    event_id: Annotated[Optional[int], Form()] = None,
    payload: Annotated[Optional[str], Form()] = None,
    files: Annotated[Optional[list[UploadFile]], File()] = None,
) -> BraceletUploadOut:
    try:
        bid = normalize_bracelet_id(bracelet_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "payload must be JSON") from exc
    if not isinstance(data, dict):
        data = {"data": data}  # keep lists/scalars too, wrapped so the column stays an object

    files = files or []
    if len(files) > MAX_FILES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"at most {MAX_FILES} files per upload")

    # Work out who this bracelet belonged to. If we can't, keep the data
    # anyway (with no user) so nothing a bracelet sends is ever lost.
    query = select(BraceletAssignment).where(BraceletAssignment.bracelet_id == bid)
    if event_id is not None:
        query = query.where(BraceletAssignment.event_id == event_id)
    matches = session.exec(query).all()
    if len(matches) > 1:
        # Bracelets are reused across events. Guessing "the latest" could tie
        # one person's recorded audio to the next wearer, so make the sender
        # say which event the data is from.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "this bracelet has been used at more than one event; send event_id",
        )
    assignment = matches[0] if matches else None

    if assignment is not None:
        resolved_event = assignment.event_id
    else:
        # Keep the event the bracelet named, if it's real, so organizers can
        # still find the data later.
        resolved_event = event_id if event_id is not None and session.get(Event, event_id) else None

    upload = BraceletUpload(
        bracelet_id=bid,
        event_id=resolved_event,
        user_id=assignment.user_id if assignment else None,
        payload=data,
    )
    session.add(upload)
    session.commit()  # need the id to name the folder
    session.refresh(upload)

    # Stream each file to disk in chunks so big audio never sits in memory.
    folder = storage.upload_dir(settings.media_dir, upload.id)
    saved: list[str] = []
    try:
        for i, f in enumerate(files):
            name = f"{i:03d}-{storage.safe_filename(f.filename, 'file')}"
            target = folder / name
            size = 0
            with target.open("wb") as out:
                while chunk := f.file.read(_CHUNK):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"{f.filename} is over 100 MB")
                    out.write(chunk)
            saved.append(target.relative_to(settings.media_dir).as_posix())
    except BaseException:
        # Don't leave half an upload behind: remove the files and the row.
        storage.delete_upload_dir(settings.media_dir, upload.id)
        session.delete(upload)
        session.commit()
        raise

    upload.file_paths = saved
    for rel in saved:
        storage.mirror_save(session, settings, rel)
    session.add(upload)
    session.commit()

    return BraceletUploadOut(
        id=upload.id,
        bracelet_id=upload.bracelet_id,
        event_id=upload.event_id,
        user_id=upload.user_id,
        status=upload.status,
        files=len(saved),
    )

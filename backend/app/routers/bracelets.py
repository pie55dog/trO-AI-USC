"""Endpoints the bracelets call (all need the X-Bracelet-Key header).

    GET  /bracelets/{id}/status   has anyone claimed this bracelet yet? (polled at boot)
    POST /bracelets/tap           live tap: "I'm touching that bracelet" (see app/taps.py)
    POST /bracelets/star          star the wearer's latest connection (button click)
    POST /bracelets/uploads       end-of-event upload (store only, for the mic build)

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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session, select

from .. import storage, taps
from ..bracelets import normalize_bracelet_id
from ..config import Settings
from ..db import get_session
from ..models import BraceletAssignment, BraceletUpload, Event, Preferences, User
from ..schemas import BraceletStatusOut, BraceletUploadOut, StarIn, StarOut, TapIn, TapOut
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

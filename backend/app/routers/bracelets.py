"""Receiving data from bracelets (PLACEHOLDER: store only, no processing).

    POST /bracelets/uploads   (header X-Bracelet-Key)

At the end of an event each bracelet (or the phone hotspot relaying for it)
sends what it collected. The exact format belongs to the hardware team, so
this endpoint is deliberately loose. It accepts a multipart form with:

    bracelet_id   required, the ESP32's id
    event_id      optional; if missing we use the bracelet's latest assignment
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

from .. import storage
from ..bracelets import normalize_bracelet_id
from ..config import Settings
from ..db import get_session
from ..models import BraceletAssignment, BraceletUpload, Event
from ..schemas import BraceletUploadOut
from ..security import get_settings, require_bracelet

router = APIRouter(prefix="/bracelets", tags=["bracelets"], dependencies=[Depends(require_bracelet)])

MAX_FILE_BYTES = 100 * 1024 * 1024  # ~100 MB per file is far beyond a night of compressed audio
MAX_FILES = 200
_CHUNK = 1024 * 1024


@router.post("/uploads", response_model=BraceletUploadOut, status_code=status.HTTP_201_CREATED)
async def receive_upload(
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
    assignment = session.exec(query.order_by(BraceletAssignment.assigned_at.desc())).first()

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
                while chunk := await f.read(_CHUNK):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"{f.filename} is over 100 MB")
                    out.write(chunk)
            saved.append(target.relative_to(settings.media_dir).as_posix())
    except BaseException:
        # Don't leave half an upload behind: remove the files and the row.
        for p in folder.iterdir():
            p.unlink(missing_ok=True)
        folder.rmdir()
        session.delete(upload)
        session.commit()
        raise

    upload.file_paths = saved
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

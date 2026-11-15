"""Conversation notes and voice notes (signed-in attendee only sees their own).

    GET   /events/{id}/notes                        everything: per person + other notes
    GET   /events/{id}/notes/{user_id}              one person you met: summary, promises, your voice notes
    PATCH /events/{id}/voice-notes/{note_id}        move a voice note to someone else / a category
    POST  /admin/process                            (organizer) finish recordings still waiting
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from .. import notes, recordings
from ..config import Settings
from ..db import get_session
from ..models import ConversationNote, User, VoiceNote
from ..schemas import ConversationNotesOut, EventNotesOut, PersonNotesOut, VoiceNoteMove, VoiceNoteOut
from ..security import current_user, get_settings, require_admin
from .events import _event_or_404, connection_out

router = APIRouter(tags=["notes"])

DB = Annotated[Session, Depends(get_session)]
Me = Annotated[User, Depends(current_user)]


def conversation_out(n: Optional[ConversationNote]) -> Optional[ConversationNotesOut]:
    if n is None:
        return None
    return ConversationNotesOut(
        summary=n.summary,
        topics=n.topics,
        about_them=n.about_them,
        commitments=n.commitments,
        follow_ups=n.follow_ups,
        transcript=n.transcript,
        speaker_method=n.speaker_method,
        updated_at=n.updated_at,
    )


def voice_out(v: VoiceNote, names: dict[int, tuple[int, str]]) -> VoiceNoteOut:
    who = names.get(v.connection_id) if v.connection_id else None
    return VoiceNoteOut(
        id=v.id,
        category=v.category,
        text=v.text,
        follow_up=v.follow_up,
        matched_by=v.matched_by,
        recorded_at=v.recorded_at,
        person_user_id=who[0] if who else None,
        person_name=who[1] if who else None,
    )


def person_out(p: notes.PersonNotes, names) -> PersonNotesOut:
    return PersonNotesOut(
        person=connection_out(p),
        conversation_status=p.conversation_status,
        conversation=conversation_out(p.conversation),
        voice_notes=[voice_out(v, names) for v in p.voice_notes],
    )


def _names(data: notes.EventNotes) -> dict[int, tuple[int, str]]:
    return {p.who.connection.id: (p.who.person.id, p.who.person.name) for p in data.people}


@router.get("/events/{event_id}/notes", response_model=EventNotesOut)
def my_notes(event_id: int, user: Me, session: DB) -> EventNotesOut:
    _event_or_404(session, event_id)
    data = notes.event_notes(session, event_id, user.id, newest_first=True)
    names = _names(data)
    return EventNotesOut(
        people=[person_out(p, names) for p in data.people],
        other=[voice_out(v, names) for v in data.other],
        voice_notes_processing=data.voice_notes_processing,
    )


@router.get("/events/{event_id}/notes/{person_id}", response_model=PersonNotesOut)
def notes_on_person(event_id: int, person_id: int, user: Me, session: DB) -> PersonNotesOut:
    _event_or_404(session, event_id)
    data = notes.event_notes(session, event_id, user.id)
    for p in data.people:
        if p.who.person.id == person_id:
            return person_out(p, _names(data))
    raise HTTPException(status.HTTP_404_NOT_FOUND, "you didn't connect with this person at this event")


@router.patch("/events/{event_id}/voice-notes/{note_id}", response_model=VoiceNoteOut)
def move_voice_note(event_id: int, note_id: int, body: VoiceNoteMove, user: Me, session: DB) -> VoiceNoteOut:
    """Fix where the AI sorted a voice note. A hand-made move is never undone by re-processing."""
    note = session.get(VoiceNote, note_id)
    if note is None or note.user_id != user.id or note.event_id != event_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "voice note not found")
    data = notes.event_notes(session, event_id, user.id)
    names = _names(data)
    if body.person_user_id is not None:
        match = next((p for p in data.people if p.who.person.id == body.person_user_id), None)
        if match is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "you didn't connect with that person")
        note.connection_id, note.category = match.who.connection.id, "person"
    else:
        if body.category in (None, "person"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "pick a person or a category (idea, task, other)")
        note.connection_id, note.category = None, body.category
    note.matched_by = "user"
    session.add(note)
    session.commit()
    session.refresh(note)
    return voice_out(note, names)


@router.post("/admin/process", dependencies=[Depends(require_admin)])
def process_waiting(
    request: Request,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
    event_id: Optional[int] = None,
) -> dict:
    """Finish every recording that is still waiting (e.g. right after adding AI_API_KEY)."""
    report = recordings.process_pending(session, settings, request.app.state.ai_factory, event_id)
    return report.__dict__


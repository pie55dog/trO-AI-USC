"""Reading notes back: what one person sees about the people they met.

Shared by the app (routers/notes.py, the connection cards) and the summary
email, so both show the same thing. Everything is scoped to one reader:
you only ever see your own conversation notes and your own voice notes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, col, select

from .connections import ConnectedPerson, connected_people
from .models import ConversationNote, Recording, VoiceNote

PENDING = ("received", "waiting_for_ai", "transcribed", "measured", "failed")


@dataclass
class PersonNotes:
    who: ConnectedPerson
    conversation: Optional[ConversationNote]
    # "not_recorded", "processing", "waiting_for_ai", "ready", "failed" or "expired"
    conversation_status: str
    voice_notes: list[VoiceNote] = field(default_factory=list)

    @property
    def follow_ups(self) -> list[str]:
        items = list(self.conversation.follow_ups) if self.conversation else []
        items += [v.follow_up for v in self.voice_notes if v.follow_up]
        return items


@dataclass
class EventNotes:
    people: list[PersonNotes]
    # Voice notes not about anyone: ideas, tasks, other.
    other: list[VoiceNote]
    # Voice notes still being transcribed or sorted.
    voice_notes_processing: int


def _status(note: Optional[ConversationNote], recorded: bool, clip_statuses: list[str]) -> str:
    if note is not None:
        return "ready"
    if not recorded or not clip_statuses:
        return "not_recorded"
    if "waiting_for_ai" in clip_statuses:
        return "waiting_for_ai"
    if any(s in ("received", "transcribed", "measured") for s in clip_statuses):
        return "processing"
    if "failed" in clip_statuses:
        return "failed"
    return "expired"


def event_notes(session: Session, event_id: int, user_id: int, *, newest_first: bool = False) -> EventNotes:
    """All of ``user_id``'s notes for the event, grouped by person."""
    people = connected_people(session, event_id, user_id, newest_first=newest_first)
    conn_ids = [p.connection.id for p in people]
    convo = {
        n.connection_id: n
        for n in session.exec(
            select(ConversationNote).where(
                ConversationNote.user_id == user_id, col(ConversationNote.connection_id).in_(conn_ids)
            )
        ).all()
    } if conn_ids else {}
    clips: dict[int, list[str]] = defaultdict(list)
    if conn_ids:
        for cid, st in session.exec(
            select(Recording.connection_id, Recording.status).where(
                Recording.kind == "conversation", col(Recording.connection_id).in_(conn_ids)
            )
        ).all():
            clips[cid].append(st)
    voice = session.exec(
        select(VoiceNote)
        .where(VoiceNote.event_id == event_id, VoiceNote.user_id == user_id)
        .order_by(col(VoiceNote.recorded_at))
    ).all()
    by_conn: dict[Optional[int], list[VoiceNote]] = defaultdict(list)
    known = set(conn_ids)
    for v in voice:
        by_conn[v.connection_id if v.connection_id in known else None].append(v)
    processing = session.exec(
        select(Recording.id).where(
            Recording.event_id == event_id,
            Recording.user_id == user_id,
            Recording.kind == "voice_note",
            col(Recording.status).in_(PENDING),
        )
    ).all()
    return EventNotes(
        people=[
            PersonNotes(
                who=p,
                conversation=convo.get(p.connection.id),
                conversation_status=_status(convo.get(p.connection.id), p.connection.recorded, clips.get(p.connection.id, [])),
                voice_notes=by_conn.get(p.connection.id, []),
            )
            for p in people
        ],
        other=by_conn.get(None, []),
        voice_notes_processing=len(processing),
    )

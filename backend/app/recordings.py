"""Bracelet audio -> transcripts -> notes.

    bracelet ──POST /bracelets/recordings──► save_recording()      (consent checked first)
                                               │  background
                                               ▼
                                         process_recording()
                    measure loudness (no AI) ─┤
              transcribe (Whisper, if needed) ─┤
                          delete the audio ───┘
                                               │
                 conversation ─► process_conversation(): who said what (speakers.py)
                                               + both people's notes (notes_ai.py)
                 voice note   ─► sort it to a person / idea / task (notes_ai.py)

Every step is safe to run again. Anything that couldn't finish (no AI key
yet, the AI service was busy) is picked up by ``process_pending``, which
runs before the summary emails go out and from POST /admin/process.

Privacy: audio is deleted as soon as it has been transcribed and measured.
Transcripts and loudness data are deleted by ``purge_event`` once the
summary emails are sent. The notes themselves stay: they're the product.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, or_, select

from . import speakers, storage
from .ai import AIClient, AIError
from .config import Settings
from .connections import connected_people
from .models import Connection, ConversationNote, Preferences, Recording, User, VoiceNote, utcnow
from .notes_ai import Candidate, Person, sort_voice_note, summarize_conversation

log = logging.getLogger("tro.recordings")

KINDS = ("conversation", "voice_note")
MAX_RECORDING_BYTES = 24 * 1024 * 1024  # what the free transcription plan accepts in one file

AIFactory = Callable[[], AIClient]

# One conversation's two clips often arrive together; process each
# conversation one at a time so they don't both write its notes at once.
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(connection_id: int) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(connection_id, threading.Lock())


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands datetimes back without a timezone; they were stored as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# --- Consent ----------------------------------------------------------------------


class ConsentError(Exception):
    """Someone in the conversation hasn't agreed to be recorded."""


def both_consent(session: Session, conn: Connection) -> bool:
    """True only if both people currently say yes to recording.

    Checked when the audio arrives (not only at the tap), so someone who
    turned recording off mid-event is never recorded after that.
    """
    for uid in (conn.user_a_id, conn.user_b_id):
        prefs = session.get(Preferences, uid)
        if not (prefs and prefs.recording_consent):
            return False
    return True


# --- Saving -------------------------------------------------------------------------


def _ext(content_type: str, data: bytes) -> str:
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[4:8] == b"ftyp":
        return ".m4a"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return ".mp3"
    return {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/webm": ".webm", "audio/mpeg": ".mp3"}.get(content_type, ".bin")


def save_recording(
    session: Session,
    settings: Settings,
    *,
    kind: str,
    event_id: int,
    user_id: int,
    bracelet_id: str,
    data: bytes,
    content_type: str = "audio/wav",
    connection: Optional[Connection] = None,
    started_at: Optional[datetime] = None,
) -> Recording:
    """Store one clip and return its row (status "received").

    Raises ConsentError for a conversation either person hasn't agreed to
    record; nothing is written in that case.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not data:
        raise ValueError("the recording is empty")
    if kind == "conversation":
        if connection is None:
            raise ValueError("a conversation recording needs its connection")
        if not both_consent(session, connection):
            raise ConsentError("both people must agree to recording; this audio was not kept")
        connection.recorded = True
        session.add(connection)

    duration = None
    try:
        samples, rate = speakers.decode_wav(data)
        duration = round(len(samples) / rate, 2) if rate else None
    except ValueError:
        pass
    now = utcnow()
    rec = Recording(
        kind=kind,
        event_id=event_id,
        user_id=user_id,
        bracelet_id=bracelet_id,
        connection_id=connection.id if connection else None,
        # No clock from the bracelet: it uploads right after it stops, so
        # "now minus the length" is close to when it started.
        started_at=started_at or (now - timedelta(seconds=duration or 0)),
        received_at=now,
        duration_s=duration,
        content_type=content_type or "application/octet-stream",
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)

    rel = f"recordings/{rec.id}{_ext(content_type, data)}"
    target = settings.media_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    rec.audio_path = rel
    # Render's free disk is wiped on restart: keep a copy until it's processed.
    storage.mirror_save(session, settings, rel, data)
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _load_audio(session: Session, settings: Settings, rec: Recording) -> Optional[bytes]:
    if not rec.audio_path:
        return None
    path = storage.resolve_media(settings.media_dir, rec.audio_path)
    if path is not None and not path.is_file():
        path = storage.mirror_restore(session, settings, rec.audio_path)
    return path.read_bytes() if path is not None and path.is_file() else None


def _delete_audio(session: Session, settings: Settings, rec: Recording) -> None:
    if not rec.audio_path:
        return
    rel = rec.audio_path
    storage.mirror_delete(session, settings, rel_path=rel)
    rec.audio_path = None
    session.add(rec)
    session.commit()
    storage.delete_media(settings.media_dir, rel)


# --- Processing -----------------------------------------------------------------------


def _siblings(session: Session, rec: Recording) -> list[Recording]:
    if rec.connection_id is None:
        return []
    return list(
        session.exec(
            select(Recording).where(
                Recording.connection_id == rec.connection_id,
                Recording.kind == "conversation",
                Recording.id != rec.id,
            )
        ).all()
    )


def _get_ai(ai_factory: AIFactory) -> AIClient:
    return ai_factory()


def process_recording(session: Session, settings: Settings, ai_factory: AIFactory, recording_id: int) -> Recording:
    """Measure and (if needed) transcribe one clip, then build its notes. Safe to repeat."""
    rec = session.get(Recording, recording_id)
    if rec is None:
        raise LookupError(recording_id)
    audio = _load_audio(session, settings, rec)

    # 1. Loudness envelope: plain math, no AI, so it works even without a key.
    if rec.envelope is None and audio is not None:
        try:
            samples, rate = speakers.decode_wav(audio)
            rec.envelope = speakers.envelope(samples, rate)
            rec.duration_s = round(len(samples) / rate, 2) if rate else rec.duration_s
        except ValueError:
            rec.envelope = []  # not WAV (e.g. a phone's webm): speakers come from context
        session.add(rec)
        session.commit()

    # 2. Transcript. A conversation needs only one: the first clip to arrive
    #    is transcribed; the other bracelet's clip is only measured.
    needs_text = rec.transcript is None and (
        rec.kind == "voice_note" or not any(s.transcript for s in _siblings(session, rec))
    )
    if needs_text:
        if audio is None:
            rec.status, rec.error = "failed", "audio missing"
            session.add(rec)
            session.commit()
            return rec
        try:
            ai = _get_ai(ai_factory)
            rec.transcript = ai.transcribe(audio, Path(rec.audio_path or "audio.wav").name, rec.content_type)
        except AIError as exc:
            rec.status = "waiting_for_ai" if not settings.ai_configured else "failed"
            rec.error = str(exc)[:500]
            session.add(rec)
            session.commit()
            return rec
        rec.status, rec.error = "transcribed", None
    elif rec.status in ("received", "waiting_for_ai", "failed"):
        rec.status, rec.error = "measured", None
    session.add(rec)
    session.commit()

    # 3. The audio has done its job.
    _delete_audio(session, settings, rec)

    # 4. Notes.
    try:
        if rec.kind == "conversation" and rec.connection_id is not None:
            made = process_conversation(session, ai_factory, rec.connection_id)
            if not made and rec.transcript is not None and not rec.transcript:
                rec.status, rec.error = "done", "nothing was said"
                session.add(rec)
                session.commit()
        elif rec.kind == "voice_note":
            process_voice_note(session, ai_factory, rec)
    except AIError as exc:
        rec.status = "waiting_for_ai" if not settings.ai_configured else "failed"
        rec.error = str(exc)[:500]
        session.add(rec)
        session.commit()
    return rec


def _person(user: User, key: str) -> Person:
    headline = user.position or " · ".join(p for p in (user.major, user.school) if p)
    return Person(key=key, user_id=user.id, name=user.name, headline=headline or "")


def process_conversation(session: Session, ai_factory: AIFactory, connection_id: int) -> bool:
    """Write both people's notes for one conversation. Returns False if nothing to do yet.

    Uses the transcribed clip as the main one and the other bracelet's clip
    (if it arrived) to tell the speakers apart. Re-running after the second
    clip arrives improves who-said-what; the notes are replaced.
    """
    with _lock_for(connection_id):
        conn = session.get(Connection, connection_id)
        if conn is None:
            return False
        clips = session.exec(
            select(Recording).where(Recording.connection_id == connection_id, Recording.kind == "conversation")
        ).all()
        transcribed = [c for c in clips if c.transcript]
        if not transcribed:
            return False
        main = max(transcribed, key=lambda c: (len(c.transcript or []), c.duration_s or 0))
        segments = main.transcript or []
        if not segments:
            return False
        other = next((c for c in clips if c.id != main.id and c.user_id != main.user_id and c.envelope), None)
        gap = None
        if other is not None and main.started_at and other.started_at:
            gap = (_aware(other.started_at) - _aware(main.started_at)).total_seconds()
        attribution = speakers.attribute(segments, main.envelope or None, other.envelope if other else None, gap)

        me = session.get(User, main.user_id)
        them_id = conn.user_b_id if conn.user_a_id == main.user_id else conn.user_a_id
        them = session.get(User, them_id)
        if me is None or them is None:
            return False
        a, b = _person(me, "A"), _person(them, "B")
        result = summarize_conversation(_get_ai(ai_factory), a, b, segments, attribution.labels)
        method = attribution.method if attribution.method != "none" else "context"

        for p in (a, b):
            n = result.notes[p.key]
            lines = [
                {
                    "speaker": "you" if lab == p.key else "them" if lab in ("A", "B") else "unsure",
                    "text": str(seg.get("text", "")).strip(),
                    "start": round(float(seg.get("start", 0)), 1),
                }
                for seg, lab in zip(segments, result.labels)
            ]
            row = session.exec(
                select(ConversationNote).where(
                    ConversationNote.connection_id == connection_id, ConversationNote.user_id == p.user_id
                )
            ).first() or ConversationNote(connection_id=connection_id, user_id=p.user_id)
            row.summary, row.topics, row.about_them = n.summary, n.topics, n.about_them
            row.commitments, row.follow_ups, row.transcript = n.commitments, n.follow_ups, lines
            row.speaker_method, row.updated_at = method, utcnow()
            session.add(row)
        for c in clips:
            if c.status in ("transcribed", "measured"):
                c.status = "done"
                session.add(c)
        try:
            session.commit()
        except IntegrityError:  # pragma: no cover - guarded by the lock
            session.rollback()
            return False
        return True


def process_voice_note(session: Session, ai_factory: AIFactory, rec: Recording) -> Optional[VoiceNote]:
    """Sort one transcribed voice note to a person or a category."""
    text = " ".join(str(s.get("text", "")).strip() for s in rec.transcript or []).strip()
    existing = session.exec(select(VoiceNote).where(VoiceNote.recording_id == rec.id)).first()
    if not text:
        rec.status, rec.error = "done", "nothing was said"
        session.add(rec)
        session.commit()
        return existing
    candidates = [
        Candidate(
            connection_id=c.connection.id,
            name=c.person.name,
            headline=c.person.position or " · ".join(p for p in (c.person.major, c.person.school) if p),
            tapped_at=_aware(c.connection.tapped_at),
        )
        for c in connected_people(session, rec.event_id, rec.user_id)
    ]
    recorded_at = _aware(rec.started_at) or utcnow()
    result = sort_voice_note(_get_ai(ai_factory), text, recorded_at, candidates)
    note = existing or VoiceNote(recording_id=rec.id, event_id=rec.event_id, user_id=rec.user_id)
    if existing is None or existing.matched_by != "user":  # never undo a move the person made by hand
        note.category, note.connection_id, note.matched_by = result.category, result.connection_id, result.matched_by
    note.text, note.follow_up, note.recorded_at = result.text, result.follow_up, recorded_at
    session.add(note)
    rec.status, rec.error = "done", None
    session.add(rec)
    session.commit()
    session.refresh(note)
    return note


@dataclass
class ProcessReport:
    processed: int = 0
    waiting: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def process_pending(session: Session, settings: Settings, ai_factory: AIFactory, event_id: Optional[int] = None) -> ProcessReport:
    """Finish every recording that isn't done (e.g. after adding the AI key)."""
    report = ProcessReport()
    query = select(Recording.id).where(col(Recording.status).in_(["received", "waiting_for_ai", "failed", "transcribed", "measured"]))
    if event_id is not None:
        query = query.where(Recording.event_id == event_id)
    for rid in session.exec(query.order_by(Recording.id)).all():
        try:
            rec = process_recording(session, settings, ai_factory, rid)
        except Exception as exc:  # one bad clip must not stop the rest
            log.exception("processing recording %s failed", rid)
            session.rollback()
            report.failed += 1
            report.errors.append(f"recording {rid}: {exc}")
            continue
        if rec.status == "done":
            report.processed += 1
        elif rec.status == "waiting_for_ai":
            report.waiting += 1
        else:
            report.failed += 1
            if rec.error:
                report.errors.append(f"recording {rid}: {rec.error}")
    return report


def run_in_background(engine, settings: Settings, ai_factory: AIFactory, recording_id: int) -> None:
    """Background-task entry point: its own database session, never raises."""
    try:
        with Session(engine) as session:
            process_recording(session, settings, ai_factory, recording_id)
    except Exception:  # pragma: no cover - logged for the organizer
        log.exception("processing recording %s failed", recording_id)


# --- Privacy -------------------------------------------------------------------------------


def purge_event(session: Session, settings: Settings, event_id: int) -> int:
    """Delete every clip's audio, transcript and loudness data for an event.

    Runs after the summary emails go out. Notes (summaries, promises, voice
    notes) stay. Returns how many recordings were cleared.
    """
    count = 0
    recs = session.exec(select(Recording).where(Recording.event_id == event_id)).all()
    for rec in recs:
        if rec.audio_path:
            _delete_audio(session, settings, rec)
        if rec.transcript is not None or rec.envelope is not None or rec.status != "done":
            rec.transcript, rec.envelope = None, None
            if rec.status != "done":
                rec.status, rec.error = "expired", "deleted after the summary email before it could be processed"
            session.add(rec)
            count += 1
    conn_ids = select(Connection.id).where(Connection.event_id == event_id)
    for note in session.exec(select(ConversationNote).where(col(ConversationNote.connection_id).in_(conn_ids))).all():
        if note.transcript:
            note.transcript = []
            session.add(note)
    session.commit()
    return count


def delete_for_user(session: Session, settings: Settings, user_id: int, connection_ids) -> list[str]:
    """Stage deletion of everything audio/notes-related tied to a user. Returns files to remove after commit.

    ``connection_ids`` is a subquery of the user's connections: clips and
    notes from those conversations include their voice, so they go too.
    Other people's own voice notes about this user are kept but unlinked.
    """
    files = []
    for note in session.exec(
        select(VoiceNote).where(or_(VoiceNote.user_id == user_id, col(VoiceNote.connection_id).in_(connection_ids)))
    ).all():
        if note.user_id == user_id:
            session.delete(note)
        else:
            note.connection_id, note.category, note.matched_by = None, "other", ""
            session.add(note)
    for note in session.exec(
        select(ConversationNote).where(
            or_(ConversationNote.user_id == user_id, col(ConversationNote.connection_id).in_(connection_ids))
        )
    ).all():
        session.delete(note)
    session.flush()
    for rec in session.exec(
        select(Recording).where(or_(Recording.user_id == user_id, col(Recording.connection_id).in_(connection_ids)))
    ).all():
        for vn in session.exec(select(VoiceNote).where(VoiceNote.recording_id == rec.id)).all():
            vn.recording_id = None
            session.add(vn)
        if rec.audio_path:
            storage.mirror_delete(session, settings, rel_path=rec.audio_path)
            files.append(rec.audio_path)
        session.delete(rec)
    session.flush()
    return files

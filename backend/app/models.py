"""Database tables.

The shape follows the sign-up spec in hackathon-project-context.md (section 5)
and the user flow in section 4:

    User ──1:1── Preferences
      │
      └──< BraceletAssignment >── Event      (a bracelet is your ticket to one event)
                                    │
           Connection (two users who tapped at an event)
           TapReport (one bracelet saying "I'm touching that one"; two matching reports make a Connection)
           Star (a user starred a connection with the bracelet button)
           BraceletUpload (raw data a bracelet sent; stored, not processed yet)
           EmailLog (one post-event email per attendee per event)

    Conversation audio and notes (app/conversations.py, app/voice_notes.py):
           Recording (one audio clip from one bracelet: a conversation or a voice note)
           ConversationNote (one person's AI notes on one conversation; two per conversation)
           VoiceNote (a note the wearer spoke between conversations, sorted to a person or category)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column, LargeBinary, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware 'now' so every stored timestamp is unambiguous UTC."""
    return datetime.now(timezone.utc)


# Contact fields a user can choose to share when they tap bracelets.
# Name and photo are always shared: a connection without them is useless.
SHAREABLE_FIELDS = ("email", "linkedin_url", "company", "website", "portfolio_url", "instagram")


class User(SQLModel, table=True):
    # AUTOINCREMENT stops SQLite from reusing a deleted user's id. Login
    # tokens carry only the id, so a reused id would let a deleted account's
    # old token sign in as the new user.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Optional[int] = Field(default=None, primary_key=True)

    # LinkedIn's stable per-app member id ("sub" claim). Unique per person.
    linkedin_sub: Optional[str] = Field(default=None, index=True, unique=True)

    # --- Required profile fields (sign-up spec) ---------------------------
    name: str
    # Prefilled from LinkedIn when available. Users may switch to a USC email,
    # which the spec prefers. This is where the post-event email goes.
    email: Optional[str] = Field(default=None, index=True, unique=True)
    school: Optional[str] = None
    major: Optional[str] = None
    bio: Optional[str] = None
    interests: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

    # --- Optional profile fields ------------------------------------------
    # e.g. "SWE intern at Snap". Typed by the user: LinkedIn's sign-in API
    # doesn't expose it.
    position: Optional[str] = None
    linkedin_url: Optional[str] = None
    company: Optional[str] = None
    website: Optional[str] = None
    portfolio_url: Optional[str] = None
    instagram: Optional[str] = None

    # Path (relative to MEDIA_DIR) of the stored headshot. We copy the
    # LinkedIn picture to our own storage because LinkedIn's image URLs expire.
    photo_path: Optional[str] = None

    # Part of every login token. Incrementing it invalidates all of this
    # user's existing tokens (see security.current_user).
    session_version: int = 0

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Preferences(SQLModel, table=True):
    """Per-user choices. One row per user, created when they first save them."""

    user_id: int = Field(foreign_key="user.id", primary_key=True)

    # Recording consent must be an explicit yes/no (spec section 5). There is
    # deliberately no default: the column stays NULL until the user chooses,
    # and onboarding is not complete until it is set.
    recording_consent: Optional[bool] = None
    # When the current consent answer was given, for an audit trail.
    recording_consent_updated_at: Optional[datetime] = None

    # "Do you want personalized connection recommendations?" Also an
    # explicit yes/no (the preferences screen requires both answers).
    recommendations_opt_in: Optional[bool] = None

    # Whether to receive the next-morning summary email.
    summary_email_opt_in: bool = True

    # Which optional contact fields are exchanged on a tap (subset of SHAREABLE_FIELDS).
    shared_fields: list[str] = Field(
        default_factory=lambda: list(SHAREABLE_FIELDS), sa_column=Column(JSON, nullable=False)
    )

    updated_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    """A networking event (career fair, club mixer, industry night)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    location: Optional[str] = None
    starts_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class BraceletAssignment(SQLModel, table=True):
    """Ties one physical bracelet (its ESP32 id) to one attendee at one event.

    Bracelets may be returned and reused, so the same bracelet id can appear
    at many events, but only once per event. A user also gets only one
    bracelet per event.
    """

    __table_args__ = (
        UniqueConstraint("event_id", "bracelet_id", name="uq_event_bracelet"),
        UniqueConstraint("event_id", "user_id", name="uq_event_user"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    # The ESP32's unique id, normalized to uppercase hex without separators.
    bracelet_id: str = Field(index=True)
    assigned_at: datetime = Field(default_factory=utcnow)


class Connection(SQLModel, table=True):
    """Two attendees who tapped bracelets at an event.

    Created live when two bracelets report the same tap (see TapReport and
    app/taps.py). The dashboard and the post-event email read from here.

    The pair is stored once with user_a_id < user_b_id.
    """

    __table_args__ = (UniqueConstraint("event_id", "user_a_id", "user_b_id", name="uq_connection"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    user_a_id: int = Field(foreign_key="user.id", index=True)
    user_b_id: int = Field(foreign_key="user.id", index=True)
    tapped_at: datetime = Field(default_factory=utcnow)
    # Whether the bracelets actually recorded this conversation (both people
    # had consented at tap time). Stored, not recomputed, so changing consent
    # later never rewrites what happened.
    recorded: bool = False


class TapReport(SQLModel, table=True):
    """One bracelet saying "I'm being held against that bracelet right now".

    Bracelets find each other over ESP-NOW and each one reports the tap to
    POST /bracelets/tap, retrying a few times a second. When the two reports
    agree (A says B and B says A, within a few seconds) the server creates
    the Connection and both bracelets get "paired" on their next try.

    ``peer_bracelet_id`` is empty for a manual tap (button held), which pairs
    with any other report at the same event in the same few seconds.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    bracelet_id: str = Field(index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    peer_bracelet_id: str = ""
    rssi: Optional[int] = None
    first_at: datetime = Field(default_factory=utcnow)
    last_at: datetime = Field(default_factory=utcnow, index=True)
    # Set once this report has been paired into a connection.
    connection_id: Optional[int] = Field(default=None, foreign_key="connection.id")


class Star(SQLModel, table=True):
    """A user starred one of their connections (short press on the bracelet button)."""

    __table_args__ = (UniqueConstraint("connection_id", "user_id", name="uq_star"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    connection_id: int = Field(foreign_key="connection.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    starred_at: datetime = Field(default_factory=utcnow)


class BraceletUpload(SQLModel, table=True):
    """Raw data a bracelet sent at the end of an event.

    PLACEHOLDER: we only receive and store it. Parsing it into connections,
    transcription, and voice-note sorting come later.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    bracelet_id: str = Field(index=True)
    # Resolved from the bracelet's assignment when we can; may be NULL if the
    # bracelet was never assigned (we still keep the data so nothing is lost).
    event_id: Optional[int] = Field(default=None, foreign_key="event.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    # Whatever JSON the bracelet sent (tap log, timestamps...). Format TBD by
    # the hardware team, so we store it untouched.
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # Paths (relative to MEDIA_DIR) of any files sent with the upload (audio).
    file_paths: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # "received" for now; later "processed" / "failed".
    status: str = "received"
    received_at: datetime = Field(default_factory=utcnow)


class EmailLog(SQLModel, table=True):
    """Record of each post-event email, so a re-run never double-sends."""

    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_email_event_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    to_address: str
    # "sent" or "failed"
    status: str
    error: Optional[str] = None
    sent_at: datetime = Field(default_factory=utcnow)


class MediaFile(SQLModel, table=True):
    """A copy of a stored file (photo or bracelet upload) kept in the database.

    Only used when MEDIA_IN_DB is on, for hosts whose disk is wiped on every
    restart (Render's free tier). Files are still written to MEDIA_DIR and
    served from there; this copy puts them back after a restart.
    """

    # Same relative path as on disk, e.g. "photos/3-ab12.jpg".
    path: str = Field(primary_key=True)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class Recording(SQLModel, table=True):
    """One audio clip from one bracelet.

    ``kind`` is "conversation" (recorded during a tap, only when both people
    consented) or "voice_note" (the wearer talking to their own bracelet).
    Each bracelet in a conversation records its own clip, so a conversation
    usually has two: one where each person's own voice is the loud one.
    That difference is how we tell who said what (app/speakers.py).

    The audio is deleted as soon as it has been transcribed and measured.
    What stays is the transcript (deleted after the summary email) and a
    loudness envelope (numbers only, no speech).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # "conversation" | "voice_note"
    event_id: int = Field(foreign_key="event.id", index=True)
    # Whose bracelet recorded it (the wearer).
    user_id: int = Field(foreign_key="user.id", index=True)
    bracelet_id: str
    # The tap this conversation belongs to; empty for voice notes.
    connection_id: Optional[int] = Field(default=None, foreign_key="connection.id", index=True)
    # Wall-clock start reported by the bracelet (NTP), used to line up the two
    # clips of one conversation. Falls back to when the upload arrived.
    started_at: datetime = Field(default_factory=utcnow)
    received_at: datetime = Field(default_factory=utcnow)
    duration_s: Optional[float] = None
    # Relative to MEDIA_DIR. Cleared once the audio is deleted.
    audio_path: Optional[str] = None
    content_type: str = "audio/wav"
    # "received" -> "transcribed" (or "measured" if it only needed its
    # loudness) -> "done"; "waiting_for_ai" when no AI key is set; "failed".
    status: str = "received"
    error: Optional[str] = None
    # Whisper's segments: [{"start": s, "end": s, "text": "..."}]. Cleared after the email.
    transcript: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # Loudness every ENVELOPE_MS (dBFS), for speaker attribution. No speech content.
    envelope: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))


class ConversationNote(SQLModel, table=True):
    """What ``user_id`` gets out of one recorded conversation: notes about the other person.

    A conversation makes two of these, one per person, each written from
    that person's side ("Jordan said they'd send you...").
    """

    __table_args__ = (UniqueConstraint("connection_id", "user_id", name="uq_note_connection_user"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    connection_id: int = Field(foreign_key="connection.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    summary: str = ""
    # Short topic tags, e.g. ["GPU tooling", "summer internships"].
    topics: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Things the other person said about themselves worth remembering.
    about_them: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Promises, each {"who": "you"|"them", "what": "...", "quote": "..."}.
    # Only kept if the quote is really in the transcript.
    commitments: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Suggested next steps, e.g. "Send Jordan your portfolio link".
    follow_ups: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # The conversation line by line: [{"speaker": "you"|"them"|"unsure", "text": ..., "start": s}].
    # Cleared after the summary email, like the raw transcript.
    transcript: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # How speakers were told apart: "two_bracelets", "one_bracelet" or "context".
    speaker_method: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class VoiceNote(SQLModel, table=True):
    """A note the wearer spoke into their bracelet, sorted by the AI.

    ``category`` is "person" (about someone they met: ``connection_id`` is
    set), "idea", "task" or "other".
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    recording_id: Optional[int] = Field(default=None, foreign_key="recording.id", index=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    connection_id: Optional[int] = Field(default=None, foreign_key="connection.id", index=True)
    category: str = "other"
    # The note, cleaned up ("um"s removed), in the speaker's words.
    text: str = ""
    # A suggested next step, if the note implies one.
    follow_up: Optional[str] = None
    # "name" (they said the person's name), "ai" (the AI matched it from
    # context), "user" (moved by hand in the app) or "" (not about a person).
    matched_by: str = ""
    recorded_at: datetime = Field(default_factory=utcnow)


class WatchPairing(SQLModel, table=True):
    """A short-lived code that signs the trO Apple Watch app in (watch/README.md).

    The attendee asks for a code on their phone (signed in), then types its
    6 digits on the watch. Only a salted hash is stored; a code works once,
    for a few minutes, and asking for a new one cancels the old one.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    code_hash: str = Field(index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    used_at: Optional[datetime] = None

"""Request and response bodies for the API (what the mobile web app sees)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from .bracelets import normalize_bracelet_id
from .models import SHAREABLE_FIELDS

# Keep free text bounded so one request can't bloat the database.
_SHORT = 120
_URL = 300
_BIO = 1000
_MAX_INTERESTS = 15


def _clean(value: Optional[str]) -> Optional[str]:
    """Trim whitespace; treat empty strings as 'not provided'."""
    if value is None:
        return None
    value = value.strip()
    return value or None


# --- Profile ---------------------------------------------------------------


class ProfileUpdate(BaseModel):
    """PATCH /users/me. Every field is optional; only the ones sent change.

    Sending ``null`` (or an empty string) for an optional field clears it.
    """

    name: Optional[str] = Field(default=None, max_length=_SHORT)
    email: Optional[EmailStr] = None
    school: Optional[str] = Field(default=None, max_length=_SHORT)
    major: Optional[str] = Field(default=None, max_length=_SHORT)
    bio: Optional[str] = Field(default=None, max_length=_BIO)
    interests: Optional[list[str]] = Field(default=None, max_length=_MAX_INTERESTS)
    position: Optional[str] = Field(default=None, max_length=_SHORT)
    linkedin_url: Optional[str] = Field(default=None, max_length=_URL)
    company: Optional[str] = Field(default=None, max_length=_SHORT)
    website: Optional[str] = Field(default=None, max_length=_URL)
    portfolio_url: Optional[str] = Field(default=None, max_length=_URL)
    instagram: Optional[str] = Field(default=None, max_length=_SHORT)

    @field_validator("name", "school", "major", "bio", "position", "company", "instagram", mode="before")
    @classmethod
    def _strip(cls, v):
        return _clean(v) if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def _strip_email(cls, v):
        # Lowercase so "Trojan@USC.edu" and "trojan@usc.edu" are the same
        # account; an empty string means "clear it".
        if isinstance(v, str):
            v = _clean(v)
            return v.lower() if v else None
        return v

    @field_validator("interests")
    @classmethod
    def _clean_interests(cls, v):
        if v is None:
            return v
        seen: list[str] = []
        for item in v:
            item = (item or "").strip()[:60]
            # De-duplicate case-insensitively but keep the user's casing.
            if item and item.lower() not in {s.lower() for s in seen}:
                seen.append(item)
        return seen

    @field_validator("linkedin_url", "website", "portfolio_url", mode="before")
    @classmethod
    def _url(cls, v):
        v = _clean(v) if isinstance(v, str) else v
        if v is None:
            return v
        if re.match(r"^https?://", v, re.IGNORECASE):
            return v
        # Reject other schemes (javascript:, mailto:...) since these links end
        # up in emails. "host:8080" is a port, not a scheme, so it's allowed.
        if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", v, re.IGNORECASE):
            raise ValueError("must be a web link (http or https)")
        # Accept "linkedin.com/in/x" by adding https://.
        return "https://" + v


class SignUp(BaseModel):
    """POST /users: create an account without LinkedIn."""

    name: str = Field(min_length=1, max_length=_SHORT)
    email: EmailStr

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def _lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class ProfileOut(BaseModel):
    id: int
    name: str
    email: Optional[str]
    school: Optional[str]
    major: Optional[str]
    bio: Optional[str]
    interests: list[str]
    position: Optional[str]
    linkedin_url: Optional[str]
    company: Optional[str]
    website: Optional[str]
    portfolio_url: Optional[str]
    instagram: Optional[str]
    # API path to the headshot, or None if there isn't one yet.
    photo_url: Optional[str]


# --- Preferences -----------------------------------------------------------


class PreferencesUpdate(BaseModel):
    """PUT /users/me/preferences.

    ``recording_consent`` and ``recommendations_opt_in`` are required on
    every save and must be true or false: the spec requires an explicit
    choice, never an assumed default.
    """

    recording_consent: bool
    recommendations_opt_in: bool
    summary_email_opt_in: bool = True
    shared_fields: list[str] = Field(default_factory=lambda: list(SHAREABLE_FIELDS))

    @field_validator("shared_fields")
    @classmethod
    def _known_fields(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(SHAREABLE_FIELDS))
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(SHAREABLE_FIELDS)}")
        # Keep a stable order and drop duplicates.
        return [f for f in SHAREABLE_FIELDS if f in v]


class PreferencesOut(BaseModel):
    # None means the user hasn't chosen yet.
    recording_consent: Optional[bool]
    recording_consent_updated_at: Optional[datetime]
    recommendations_opt_in: Optional[bool]
    summary_email_opt_in: bool
    shared_fields: list[str]


# --- Onboarding status -----------------------------------------------------


class NotesPreview(BaseModel):
    """The "Conversation notes" line on a connection card."""

    # "not_recorded", "processing", "waiting_for_ai", "ready", "failed" or "expired"
    conversation: str = "not_recorded"
    voice_notes: int = 0
    follow_ups: int = 0


class ConnectionOut(BaseModel):
    """Someone the signed-in user tapped bracelets with (event dashboard)."""

    user_id: int
    name: str
    position: Optional[str]
    school: Optional[str]
    major: Optional[str]
    bio: Optional[str]
    photo_url: Optional[str]
    # Whether this conversation was recorded (both consented at tap time).
    recorded: bool
    # The signed-in user starred this person (short press on the bracelet button).
    starred: bool = False
    # Only the fields this person chose to share, e.g. {"email": "...", "linkedin_url": "..."}.
    contact: dict[str, str]
    tapped_at: datetime
    notes: NotesPreview = NotesPreview()


class Commitment(BaseModel):
    who: str  # "you" or "them"
    what: str
    quote: str


class TranscriptLine(BaseModel):
    speaker: str  # "you", "them" or "unsure"
    text: str
    start: float


class ConversationNotesOut(BaseModel):
    summary: str
    topics: list[str]
    about_them: list[str]
    commitments: list[Commitment]
    follow_ups: list[str]
    # Empty once the summary email has gone out (transcripts are deleted).
    transcript: list[TranscriptLine]
    # How speakers were told apart: "two_bracelets", "one_bracelet" or "context".
    speaker_method: str
    updated_at: datetime


class VoiceNoteOut(BaseModel):
    id: int
    category: str  # "person", "idea", "task" or "other"
    text: str
    follow_up: Optional[str]
    # "name", "ai", "user" or ""
    matched_by: str
    recorded_at: datetime
    person_user_id: Optional[int] = None
    person_name: Optional[str] = None


class PersonNotesOut(BaseModel):
    person: "ConnectionOut"
    conversation_status: str
    conversation: Optional[ConversationNotesOut]
    voice_notes: list[VoiceNoteOut]


class EventNotesOut(BaseModel):
    people: list[PersonNotesOut]
    other: list[VoiceNoteOut]
    voice_notes_processing: int


class VoiceNoteMove(BaseModel):
    """PATCH a voice note: move it to someone else or to a category."""

    person_user_id: Optional[int] = None
    category: Optional[str] = Field(default=None, pattern="^(person|idea|task|other)$")


class OnboardingStatus(BaseModel):
    """What's still missing before the user is ready for an event.

    The frontend can use ``missing`` to route the user to the right screen.
    """

    complete: bool
    missing: list[str]


class MeOut(BaseModel):
    profile: ProfileOut
    preferences: PreferencesOut
    onboarding: OnboardingStatus


class SignUpOut(BaseModel):
    token: str
    me: MeOut


# --- Events and bracelets --------------------------------------------------


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=_SHORT)
    location: Optional[str] = Field(default=None, max_length=_SHORT)
    starts_at: Optional[datetime] = None


class EventOut(BaseModel):
    id: int
    name: str
    location: Optional[str]
    starts_at: Optional[datetime]


class BraceletClaim(BaseModel):
    """POST /events/{id}/bracelet: tie a bracelet to the signed-in user."""

    bracelet_id: str = Field(min_length=1, max_length=64)

    @field_validator("bracelet_id")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_bracelet_id(v)


class BraceletAssignmentOut(BaseModel):
    event_id: int
    bracelet_id: str
    assigned_at: datetime


class BraceletUploadOut(BaseModel):
    id: int
    bracelet_id: str
    event_id: Optional[int]
    user_id: Optional[int]
    status: str
    files: int


class RecordingOut(BaseModel):
    id: int
    kind: str
    status: str
    connection_id: Optional[int] = None
    duration_s: Optional[float] = None


# --- Live taps (firmware/trO_bracelet) ---------------------------------------


def _bracelet_or_blank(v: str) -> str:
    return normalize_bracelet_id(v) if v and v.strip() else ""


class TapIn(BaseModel):
    """One bracelet reporting a tap. Sent again every few hundred ms until paired."""

    device: str = Field(description="this bracelet's id")
    peer: str = Field("", description="the bracelet it's touching; empty for a manual (button) tap")
    rssi: Optional[int] = Field(None, ge=-127, le=20)
    event_id: Optional[int] = None

    @field_validator("device")
    @classmethod
    def _device(cls, v: str) -> str:
        return normalize_bracelet_id(v)

    @field_validator("peer")
    @classmethod
    def _peer(cls, v: str) -> str:
        return _bracelet_or_blank(v)


class TapOut(BaseModel):
    status: str  # "waiting" until the other bracelet reports, then "paired"
    # The connection's id as text (kept as "session" for the original sketch).
    session: Optional[str] = None
    connection_id: Optional[int] = None
    peer_name: Optional[str] = None
    # 5-99, or null unless both people opted in to recommendations.
    match_pct: Optional[int] = None
    # Both people said yes to recording (for the mic build; the no-mic build ignores it).
    both_consented: bool = False


class StarIn(BaseModel):
    device: str
    event_id: Optional[int] = None

    @field_validator("device")
    @classmethod
    def _device(cls, v: str) -> str:
        return normalize_bracelet_id(v)


class StarOut(BaseModel):
    status: str  # "starred" or "no_connection"
    connection_id: Optional[int] = None
    peer_name: Optional[str] = None


class BraceletStatusOut(BaseModel):
    """What a bracelet checks at boot: has anyone claimed me yet?"""

    bracelet_id: str
    linked: bool
    event_id: Optional[int] = None
    first_name: Optional[str] = None
    recording_consent: Optional[bool] = None


# --- Email -----------------------------------------------------------------


class SendSummariesRequest(BaseModel):
    # Re-send to people who already got this event's email (default: skip them).
    resend: bool = False


class SendSummariesResult(BaseModel):
    sent: int
    skipped_already_sent: int
    skipped_opted_out: int
    skipped_no_email: int
    failed: int
    failures: list[str]
    recordings_purged: int = 0


class TestEmailRequest(BaseModel):
    to: EmailStr


# --- Organizer console -------------------------------------------------------


class EventUpdate(BaseModel):
    """PATCH /events/{id}. Only the fields sent change; ``null`` clears location or start time."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=_SHORT)
    location: Optional[str] = Field(default=None, max_length=_SHORT)
    starts_at: Optional[datetime] = None

    @field_validator("name", "location", mode="before")
    @classmethod
    def _strip(cls, v):
        return _clean(v) if isinstance(v, str) else v


class AttendeeOut(BaseModel):
    """One registered attendee (someone holding a bracelet for the event)."""

    user_id: int
    name: str
    email: Optional[str]
    school: Optional[str]
    major: Optional[str]
    photo_url: Optional[str]
    bracelet_id: str
    assigned_at: datetime
    recording_consent: Optional[bool]
    summary_email_opt_in: bool
    connections: int
    # "sent" / "failed" once the post-event email has been tried, else None.
    email_status: Optional[str]


class EventOverview(BaseModel):
    """Counts for the organizer console."""

    event: EventOut
    attendees: int
    recording_consent: int
    summary_email_opt_in: int
    connections: int
    uploads_received: int
    emails_sent: int
    emails_failed: int


class DeskAssign(BaseModel):
    """POST /events/{id}/attendees: link a bracelet to an attendee at the check-in desk."""

    email: EmailStr
    bracelet_id: str = Field(min_length=1, max_length=64)

    @field_validator("email", mode="before")
    @classmethod
    def _lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("bracelet_id")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_bracelet_id(v)

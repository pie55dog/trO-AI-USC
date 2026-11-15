"""Database tables.

The shape follows the sign-up spec in hackathon-project-context.md (section 5)
and the user flow in section 4:

    User ──1:1── Preferences
      │
      └──< BraceletAssignment >── Event      (a bracelet is your ticket to one event)
                                    │
           Connection (two users who tapped at an event)
           BraceletUpload (raw data a bracelet sent; stored, not processed yet)
           EmailLog (one post-event email per attendee per event)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column, UniqueConstraint
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

    Nothing writes these yet: turning bracelet uploads into connections is
    the bracelet-processing step, which is out of scope for the first run.
    The post-event email already reads from this table, so once processing
    lands the emails fill in with no further changes.

    The pair is stored once with user_a_id < user_b_id.
    """

    __table_args__ = (UniqueConstraint("event_id", "user_a_id", "user_b_id", name="uq_connection"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id", index=True)
    user_a_id: int = Field(foreign_key="user.id", index=True)
    user_b_id: int = Field(foreign_key="user.id", index=True)
    tapped_at: datetime = Field(default_factory=utcnow)


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

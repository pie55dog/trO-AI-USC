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
    linkedin_url: Optional[str] = Field(default=None, max_length=_URL)
    company: Optional[str] = Field(default=None, max_length=_SHORT)
    website: Optional[str] = Field(default=None, max_length=_URL)
    portfolio_url: Optional[str] = Field(default=None, max_length=_URL)
    instagram: Optional[str] = Field(default=None, max_length=_SHORT)

    @field_validator("name", "school", "major", "bio", "company", "instagram", mode="before")
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


class ProfileOut(BaseModel):
    id: int
    name: str
    email: Optional[str]
    school: Optional[str]
    major: Optional[str]
    bio: Optional[str]
    interests: list[str]
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

    ``recording_consent`` is required on every save and must be true or
    false: the spec requires an explicit choice, never an assumed default.
    """

    recording_consent: bool
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
    summary_email_opt_in: bool
    shared_fields: list[str]


# --- Onboarding status -----------------------------------------------------


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


class TestEmailRequest(BaseModel):
    to: EmailStr

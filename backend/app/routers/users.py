"""The signed-in user's profile, preferences and photo (onboarding screens).

    GET    /users/me               profile + preferences + what's still missing
    PATCH  /users/me               edit profile fields
    PUT    /users/me/preferences   save preferences (explicit recording consent)
    POST   /users/me/photo         upload a headshot (replaces the LinkedIn one)
    DELETE /users/me               delete the account and everything tied to it
    GET    /media/photos/{name}    serve a headshot (see note in get_photo)
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import storage
from ..config import Settings
from ..db import get_session
from ..models import (
    BraceletAssignment,
    BraceletUpload,
    Connection,
    EmailLog,
    Preferences,
    User,
    utcnow,
)
from ..schemas import (
    MeOut,
    OnboardingStatus,
    PreferencesOut,
    PreferencesUpdate,
    ProfileOut,
    ProfileUpdate,
)
from ..security import current_user, get_settings

router = APIRouter(tags=["users"])

CurrentUser = Annotated[User, Depends(current_user)]
DB = Annotated[Session, Depends(get_session)]

# Profile fields the sign-up spec marks as required (section 5).
REQUIRED_PROFILE_FIELDS = ("name", "email", "school", "major", "bio", "interests")


# --- Helpers ---------------------------------------------------------------


def photo_url(user: User) -> Optional[str]:
    if not user.photo_path:
        return None
    return f"/media/{user.photo_path}"


def profile_out(user: User) -> ProfileOut:
    return ProfileOut(
        id=user.id,
        name=user.name,
        email=user.email,
        school=user.school,
        major=user.major,
        bio=user.bio,
        interests=list(user.interests or []),
        linkedin_url=user.linkedin_url,
        company=user.company,
        website=user.website,
        portfolio_url=user.portfolio_url,
        instagram=user.instagram,
        photo_url=photo_url(user),
    )


def preferences_out(prefs: Optional[Preferences]) -> PreferencesOut:
    if prefs is None:
        # Not saved yet: consent is undecided; everything else at defaults.
        prefs = Preferences(user_id=0)
    return PreferencesOut(
        recording_consent=prefs.recording_consent,
        recording_consent_updated_at=prefs.recording_consent_updated_at,
        summary_email_opt_in=prefs.summary_email_opt_in,
        shared_fields=list(prefs.shared_fields),
    )


def onboarding_status(user: User, prefs: Optional[Preferences]) -> OnboardingStatus:
    """List what the user still has to fill in before getting a bracelet."""
    missing = [f for f in REQUIRED_PROFILE_FIELDS if not getattr(user, f)]
    if prefs is None or prefs.recording_consent is None:
        missing.append("recording_consent")
    return OnboardingStatus(complete=not missing, missing=missing)


def me_out(session: Session, user: User) -> MeOut:
    prefs = session.get(Preferences, user.id)
    return MeOut(
        profile=profile_out(user),
        preferences=preferences_out(prefs),
        onboarding=onboarding_status(user, prefs),
    )


# --- Endpoints -------------------------------------------------------------


@router.get("/users/me", response_model=MeOut)
def get_me(user: CurrentUser, session: DB) -> MeOut:
    return me_out(session, user)


@router.patch("/users/me", response_model=MeOut)
def update_me(body: ProfileUpdate, user: CurrentUser, session: DB) -> MeOut:
    changes = body.model_dump(exclude_unset=True)
    # Name is required and can't be blanked out.
    if "name" in changes and not changes["name"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "name can't be empty")
    if changes.get("email") and changes["email"] != user.email:
        taken = session.exec(select(User).where(User.email == changes["email"], User.id != user.id)).first()
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "that email is already used by another account")
    if "interests" in changes and changes["interests"] is None:
        changes["interests"] = []
    for key, value in changes.items():
        setattr(user, key, value)
    user.updated_at = utcnow()
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Another account took the email between our check and the commit.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "that email is already used by another account") from None
    session.refresh(user)
    return me_out(session, user)


@router.put("/users/me/preferences", response_model=MeOut)
def save_preferences(body: PreferencesUpdate, user: CurrentUser, session: DB) -> MeOut:
    prefs = session.get(Preferences, user.id) or Preferences(user_id=user.id)
    # Timestamp consent only when the answer actually changes, so the audit
    # trail shows when the user last *decided*, not when they last saved.
    if prefs.recording_consent != body.recording_consent:
        prefs.recording_consent_updated_at = utcnow()
    prefs.recording_consent = body.recording_consent
    prefs.summary_email_opt_in = body.summary_email_opt_in
    prefs.shared_fields = body.shared_fields
    prefs.updated_at = utcnow()
    session.add(prefs)
    session.commit()
    return me_out(session, user)


@router.post("/users/me/photo", response_model=MeOut)
def upload_photo(
    file: UploadFile,
    user: CurrentUser,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeOut:
    # Read one byte past the limit so we can tell "too big" without loading
    # an arbitrarily large file into memory.
    data = file.file.read(storage.MAX_PHOTO_BYTES + 1)
    try:
        new_path = storage.save_photo(settings.media_dir, user.id, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    old_path, user.photo_path = user.photo_path, new_path
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    storage.delete_media(settings.media_dir, old_path)
    session.refresh(user)
    return me_out(session, user)


@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    user: CurrentUser,
    session: DB,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Delete the account and every row and file tied to it.

    Raw bracelet uploads from this user's bracelet are deleted too, because
    they can contain their recorded audio.
    """
    upload_ids = []
    for upload in session.exec(select(BraceletUpload).where(BraceletUpload.user_id == user.id)).all():
        upload_ids.append(upload.id)
        session.delete(upload)
    for model, column in (
        (Connection, Connection.user_a_id),
        (Connection, Connection.user_b_id),
        (BraceletAssignment, BraceletAssignment.user_id),
        (EmailLog, EmailLog.user_id),
        (Preferences, Preferences.user_id),
    ):
        for row in session.exec(select(model).where(column == user.id)).all():
            session.delete(row)
    photo = user.photo_path
    session.delete(user)
    session.commit()
    # Remove files only after the database commit succeeded, so a failed
    # delete never leaves rows pointing at missing files.
    storage.delete_media(settings.media_dir, photo)
    for upload_id in upload_ids:
        storage.delete_upload_dir(settings.media_dir, upload_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/media/photos/{filename}", include_in_schema=False)
def get_photo(filename: str, settings: Annotated[Settings, Depends(get_settings)]) -> FileResponse:
    """Serve a headshot.

    Photos are public by URL so they work in <img> tags and in emails, but
    each file name includes a random token, so they can't be guessed or
    listed by user id.
    """
    path = storage.resolve_media(settings.media_dir, f"photos/{storage.safe_filename(filename, 'x')}")
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    media_type = storage.PHOTO_MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media_type)

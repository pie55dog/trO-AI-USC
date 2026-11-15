"""LinkedIn sign-in.

    GET /auth/linkedin/login     -> redirects the phone's browser to LinkedIn
    GET /auth/linkedin/callback  -> LinkedIn sends the user back here; we
                                    create/update the account, then redirect
                                    to the web app with a login token.

The web app receives the token in the URL *fragment*
(``FRONTEND_URL/auth/callback#token=...&new_user=1``). Fragments are never
sent to servers, so the token doesn't end up in access logs.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import linkedin, storage
from ..config import Settings
from ..db import get_session
from ..models import User, utcnow
from ..security import get_settings, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

STATE_COOKIE = "tro_oauth_state"
STATE_MAX_AGE = 10 * 60  # the user has 10 minutes to finish signing in


def _state_signer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="tro-oauth-state")


def _frontend_redirect(settings: Settings, **params: str) -> RedirectResponse:
    """Send the browser back to the web app with ``params`` in the fragment."""
    url = f"{settings.frontend_url.rstrip('/')}/auth/callback#{urlencode(params)}"
    resp = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    resp.delete_cookie(STATE_COOKIE, path="/auth")
    return resp


@router.get("/linkedin/login")
def linkedin_login(settings: Annotated[Settings, Depends(get_settings)]) -> RedirectResponse:
    """Start LinkedIn sign-in."""
    if not settings.linkedin_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LinkedIn sign-in is not configured")
    # A random state value, also stored in a signed cookie, proves the
    # callback belongs to a login this browser started (CSRF protection).
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(linkedin.authorize_url(settings, state), status_code=status.HTTP_302_FOUND)
    resp.set_cookie(
        STATE_COOKIE,
        _state_signer(settings).dumps(state),
        max_age=STATE_MAX_AGE,
        httponly=True,
        samesite="lax",  # sent on LinkedIn's top-level redirect back to us
        secure=settings.linkedin_redirect_uri.startswith("https://"),
        path="/auth",
    )
    return resp


@router.get("/linkedin/callback")
def linkedin_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Finish LinkedIn sign-in and hand the web app a login token."""
    if not settings.linkedin_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LinkedIn sign-in is not configured")

    # 1. The user cancelled on LinkedIn, or LinkedIn reported an error.
    if error:
        return _frontend_redirect(settings, error="cancelled" if error == "user_cancelled_login" else "linkedin")

    # 2. Check state against the cookie we set in /login.
    cookie = request.cookies.get(STATE_COOKIE)
    try:
        expected = _state_signer(settings).loads(cookie, max_age=STATE_MAX_AGE) if cookie else None
    except (BadSignature, SignatureExpired):
        expected = None
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return _frontend_redirect(settings, error="state")

    # 3. Talk to LinkedIn.
    with request.app.state.http_client_factory() as client:
        try:
            token = linkedin.exchange_code(settings, client, code)
            profile = linkedin.fetch_userinfo(client, token)
        except (linkedin.LinkedInError, httpx.HTTPError, ValueError) as exc:
            # ValueError covers a non-JSON body; HTTPError covers network trouble.
            log.warning("LinkedIn sign-in failed: %s", exc)
            return _frontend_redirect(settings, error="linkedin")

        user, is_new = _upsert_user(session, profile)

        # 4. Copy the headshot once. If the user later uploads their own photo
        #    we keep theirs, so we only fetch when there's no photo yet.
        if not user.photo_path and profile.picture_url:
            data = linkedin.download_picture(client, profile.picture_url)
            if data:
                try:
                    user.photo_path = storage.save_photo(settings.media_dir, user.id, data)
                except ValueError:
                    pass  # not an image we accept; the user can upload one
                else:
                    session.add(user)
                    session.commit()

    return _frontend_redirect(settings, token=issue_token(settings, user.id, user.session_version), new_user="1" if is_new else "0")


def _upsert_user(session: Session, profile: linkedin.LinkedInProfile) -> tuple[User, bool]:
    """Find the user for this LinkedIn account, creating one if needed.

    Returns (user, is_new). For returning users we don't overwrite name or
    email: they may have edited them (e.g. switched to their USC email).
    """
    user = session.exec(select(User).where(User.linkedin_sub == profile.sub)).first()
    if user is not None:
        return user, False

    email = profile.email.lower() if profile.email else None
    if email and profile.email_verified:
        owner = session.exec(select(User).where(User.email == email)).first()
        if owner is not None and owner.linkedin_sub is None:
            # Someone signed up with this email without LinkedIn (POST /users).
            # LinkedIn has verified this person owns the address, so this is
            # their account: link it. That lets people who lost their login
            # get back in, and stops an email typed by someone else from
            # locking the real owner out. Bumping session_version signs out
            # whoever created it, in case that wasn't the owner.
            owner.linkedin_sub = profile.sub
            owner.session_version += 1
            owner.updated_at = utcnow()
            session.add(owner)
            session.commit()
            session.refresh(owner)
            return owner, False
        if owner is not None:
            email = None  # belongs to a different LinkedIn account
    else:
        email = None  # never claim an unverified email

    user = User(linkedin_sub=profile.sub, name=profile.name, email=email, updated_at=utcnow())
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Two callbacks for the same person raced (e.g. a double tap), or
        # someone took the email in between. Use the winner's row, or retry
        # once without the email.
        session.rollback()
        existing = session.exec(select(User).where(User.linkedin_sub == profile.sub)).first()
        if existing is not None:
            return existing, False
        user = User(linkedin_sub=profile.sub, name=profile.name, email=None, updated_at=utcnow())
        session.add(user)
        session.commit()
    session.refresh(user)
    return user, True

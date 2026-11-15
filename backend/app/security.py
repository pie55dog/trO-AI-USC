"""Login tokens and the shared-secret checks for admins and bracelets.

Login tokens are signed (not encrypted) with SECRET_KEY using itsdangerous.
They only carry the user id, and tampering breaks the signature. The mobile
web app sends them as ``Authorization: Bearer <token>``; using a header
instead of a cookie avoids cross-site cookie problems when the frontend and
API live on different domains.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlmodel import Session

from .config import Settings
from .db import get_session
from .models import User

_LOGIN_SALT = "tro-login"


def get_settings(request: Request) -> Settings:
    """FastAPI dependency: the settings the app was created with."""
    return request.app.state.settings


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=_LOGIN_SALT)


def issue_token(settings: Settings, user_id: int) -> str:
    """Create a login token for ``user_id``."""
    return _serializer(settings).dumps({"uid": user_id})


def read_token(settings: Settings, token: str) -> Optional[int]:
    """Return the user id inside a valid, unexpired token, else None."""
    try:
        data = _serializer(settings).loads(token, max_age=settings.token_max_age)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


def current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> User:
    """FastAPI dependency: the signed-in user, or 401."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized
    user_id = read_token(settings, authorization[7:].strip())
    if user_id is None:
        raise unauthorized
    user = session.get(User, user_id)
    if user is None:  # account deleted after the token was issued
        raise unauthorized
    return user


def _check_shared_secret(expected: str, provided: Optional[str], what: str) -> None:
    """Constant-time compare of a shared secret header.

    If the secret isn't configured at all, the endpoint is disabled rather
    than left open: a forgotten env var must never mean "no auth".
    """
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{what} key is not configured on the server")
    if not provided or not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid {what} key")


def require_admin(
    settings: Annotated[Settings, Depends(get_settings)],
    x_admin_key: Annotated[Optional[str], Header()] = None,
) -> None:
    """FastAPI dependency for organizer-only endpoints (header X-Admin-Key)."""
    _check_shared_secret(settings.admin_api_key, x_admin_key, "admin")


def require_bracelet(
    settings: Annotated[Settings, Depends(get_settings)],
    x_bracelet_key: Annotated[Optional[str], Header()] = None,
) -> None:
    """FastAPI dependency for bracelet uploads (header X-Bracelet-Key)."""
    _check_shared_secret(settings.bracelet_api_key, x_bracelet_key, "bracelet")

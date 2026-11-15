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


def issue_token(settings: Settings, user_id: int, session_version: int = 0) -> str:
    """Create a login token for ``user_id``.

    ``session_version`` must match ``User.session_version``; bumping that
    column signs the user out everywhere.
    """
    return _serializer(settings).dumps({"uid": user_id, "v": session_version})


def read_token_claims(settings: Settings, token: str) -> Optional[tuple[int, int]]:
    """Return (user id, session version) from a valid, unexpired token, else None."""
    try:
        data = _serializer(settings).loads(token, max_age=settings.token_max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict):
        return None
    uid, version = data.get("uid"), data.get("v", 0)
    if not isinstance(uid, int) or not isinstance(version, int):
        return None
    return uid, version


def read_token(settings: Settings, token: str) -> Optional[int]:
    """Return the user id inside a valid, unexpired token, else None."""
    claims = read_token_claims(settings, token)
    return claims[0] if claims else None


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
    claims = read_token_claims(settings, authorization[7:].strip())
    if claims is None:
        raise unauthorized
    user = session.get(User, claims[0])
    # Account deleted, or signed out everywhere since the token was issued.
    if user is None or claims[1] != user.session_version:
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

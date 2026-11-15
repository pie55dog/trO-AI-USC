"""Sign In with LinkedIn using OpenID Connect (official LinkedIn API only).

What LinkedIn gives us (docs: learn.microsoft.com/linkedin/consumer/
integrations/self-serve/sign-in-with-linkedin-v2), with scopes
``openid profile email``:

    sub, name, given_name, family_name, picture, locale, email, email_verified

So we can autofill **name, profile picture and email**. LinkedIn does NOT
return headline, bio ("About") or current position through any self-serve
product; those need partner-only APIs. The user types bio, school, major and
company themselves during onboarding.

Flow:
  1. ``authorize_url`` -> send the browser to LinkedIn.
  2. LinkedIn redirects back with ``?code=...&state=...``.
  3. ``exchange_code`` -> access token.
  4. ``fetch_userinfo`` -> the claims above.
  5. ``download_picture`` -> bytes we store ourselves (LinkedIn's picture
     URLs are signed and expire, so we can't just keep the URL).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx

from .config import Settings

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPES = "openid profile email"

# LinkedIn's media CDN domains; we only download pictures from these.
PICTURE_HOSTS = ("licdn.com", "licdn-ei.com")

# A profile photo should never be anywhere near this; it guards memory.
MAX_PICTURE_BYTES = 5 * 1024 * 1024


class LinkedInError(Exception):
    """LinkedIn rejected a request or returned something unusable."""


@dataclass
class LinkedInProfile:
    sub: str
    name: str
    email: Optional[str]
    email_verified: bool
    picture_url: Optional[str]


def authorize_url(settings: Settings, state: str) -> str:
    """URL that starts LinkedIn sign-in. ``state`` protects against CSRF."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": SCOPES,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(settings: Settings, client: httpx.Client, code: str) -> str:
    """Trade the one-time ``code`` for an access token."""
    resp = client.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.linkedin_redirect_uri,
            "client_id": settings.linkedin_client_id,
            "client_secret": settings.linkedin_client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code != 200:
        raise LinkedInError(f"token exchange failed ({resp.status_code})")
    token = resp.json().get("access_token")
    if not token:
        raise LinkedInError("token response had no access_token")
    return token


def fetch_userinfo(client: httpx.Client, access_token: str) -> LinkedInProfile:
    """Read the member's OpenID Connect claims."""
    resp = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    if resp.status_code != 200:
        raise LinkedInError(f"userinfo failed ({resp.status_code})")
    data = resp.json()
    sub = data.get("sub")
    if not sub:
        raise LinkedInError("userinfo had no 'sub'")
    # Prefer the full name; fall back to given + family name.
    name = (data.get("name") or " ".join(
        p for p in (data.get("given_name"), data.get("family_name")) if p
    )).strip()
    return LinkedInProfile(
        sub=str(sub),
        name=name or "LinkedIn member",
        # email is optional in LinkedIn's response; handle it missing.
        email=(data.get("email") or None),
        email_verified=bool(data.get("email_verified")),
        picture_url=data.get("picture") or None,
    )


def download_picture(client: httpx.Client, url: str) -> Optional[bytes]:
    """Fetch the profile picture. Returns None on any failure.

    A missing photo should never block sign-in, so errors are swallowed and
    the user can upload a headshot themselves later.

    Only LinkedIn's media CDN (``*.licdn.com``; LinkedIn's docs example also
    shows ``*.licdn-ei.com``) over HTTPS is fetched, so a malformed response
    can't make our server request arbitrary URLs.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = any(host == d or host.endswith("." + d) for d in PICTURE_HOSTS)
    if parsed.scheme != "https" or not allowed:
        return None
    try:
        # Stream so an oversized response is cut off instead of fully buffered.
        with client.stream("GET", url, follow_redirects=False) as resp:
            if resp.status_code != 200:
                return None
            data = bytearray()
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_PICTURE_BYTES:
                    return None
            return bytes(data)
    except httpx.HTTPError:
        return None

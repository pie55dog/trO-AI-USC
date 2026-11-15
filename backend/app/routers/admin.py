"""Organizer tools (header X-Admin-Key).

    GET  /admin/check        confirm an organizer key works (the console signs in with it)
    POST /admin/email/test   send a test email to check SMTP settings
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from .. import mailer
from ..config import Settings
from ..schemas import TestEmailRequest
from ..security import get_settings, require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/check")
def check_key(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """200 if the X-Admin-Key header is right. Also says how email is set up."""
    return {"ok": True, "email_backend": settings.email_backend}


@router.post("/email/test")
def send_test_email(body: TestEmailRequest, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Send a short email so organizers can confirm email works before an event."""
    message = mailer.build_message(
        settings,
        str(body.to),
        "Tro test email",
        "If you can read this, Tro can send email.",
        "<p>If you can read this, Tro can send email.</p>",
    )
    try:
        mailer.get_backend(settings).send(message)
    except mailer.EmailError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"email failed: {exc}") from exc
    return {"sent": True, "backend": settings.email_backend}

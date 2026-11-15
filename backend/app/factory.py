"""Builds the FastAPI app. Kept separate from main.py so importing it (as the
tests do) doesn't create the default database file as a side effect.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import ai
from .config import Settings, load_settings
from .db import make_engine
from .routers import admin, auth, bracelets, events, notes, organizer, users


def create_app(
    settings: Optional[Settings] = None,
    http_client_factory: Optional[Callable[[], httpx.Client]] = None,
    ai_factory: Optional[Callable[[], "ai.AIClient"]] = None,
) -> FastAPI:
    """Build the app.

    ``settings``, ``http_client_factory`` and ``ai_factory`` are injectable so
    tests can use a temporary database, a fake LinkedIn and a fake AI
    without touching the network.
    """
    settings = settings or load_settings()
    logging.basicConfig(level=logging.INFO)
    if settings.secret_key in ("", "dev-only-change-me"):
        # Anyone who knows the key can sign login tokens for any account, so a
        # deployed server must never run with the public default.
        if os.environ.get("RENDER") or not settings.database_url.startswith("sqlite"):
            raise RuntimeError("SECRET_KEY must be set to a long random value on a deployed server")
        logging.getLogger("tro").warning("SECRET_KEY is the dev default; set a real one before deploying")

    app = FastAPI(title="Tro API", version="0.1.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.http_client_factory = http_client_factory or (lambda: httpx.Client(timeout=10))
    # Transcription + notes (Groq by default). Raises ai.AIError when no key is set.
    app.state.ai_factory = ai_factory or (lambda: ai.make_client(settings))
    settings.media_dir.mkdir(parents=True, exist_ok=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        # An API that returns JSON and photos: nothing should frame it, sniff it, or leak its URLs.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(("/docs", "/redoc")):  # the API docs page loads its own scripts
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    for module in (auth, users, events, notes, organizer, bracelets, admin):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"ok": True}

    return app

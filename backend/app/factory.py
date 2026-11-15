"""Builds the FastAPI app. Kept separate from main.py so importing it (as the
tests do) doesn't create the default database file as a side effect.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, load_settings
from .db import make_engine
from .routers import admin, auth, bracelets, events, users


def create_app(
    settings: Optional[Settings] = None,
    http_client_factory: Optional[Callable[[], httpx.Client]] = None,
) -> FastAPI:
    """Build the app.

    ``settings`` and ``http_client_factory`` are injectable so tests can use a
    temporary database and a fake LinkedIn without touching the network.
    """
    settings = settings or load_settings()
    logging.basicConfig(level=logging.INFO)
    if settings.secret_key == "dev-only-change-me":
        logging.getLogger("tro").warning("SECRET_KEY is the dev default; set a real one before deploying")

    app = FastAPI(title="Tro API", version="0.1.0")
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.http_client_factory = http_client_factory or (lambda: httpx.Client(timeout=10))
    settings.media_dir.mkdir(parents=True, exist_ok=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (auth, users, events, bracelets, admin):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"ok": True}

    return app

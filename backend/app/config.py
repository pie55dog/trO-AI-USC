"""Runtime settings for the Tro backend.

Every value comes from an environment variable so the same code runs on a
laptop, in tests, and on the demo server. See ``.env.example`` for the full
list. Nothing secret is hardcoded here: the defaults are only safe for local
development.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    """Read an environment variable, treating blank values as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    # --- Core -----------------------------------------------------------
    # SQLite keeps the hackathon setup to one file; any SQLAlchemy URL works.
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./tro.db"))
    # Signs login tokens and the OAuth state cookie. MUST be changed in prod.
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-only-change-me"))
    # How long a login token stays valid, in seconds (default: 30 days).
    token_max_age: int = field(default_factory=lambda: int(_env("TOKEN_MAX_AGE", str(60 * 60 * 24 * 30))))
    # Where profile photos and raw bracelet uploads are stored on disk.
    media_dir: Path = field(default_factory=lambda: Path(_env("MEDIA_DIR", "./media")))
    # Also keep a copy of every stored file in the database, for hosts whose
    # disk is wiped on restart (Render free tier). See storage.mirror_*.
    media_in_db: bool = field(default_factory=lambda: _env("MEDIA_IN_DB", "false").lower() == "true")
    # The mobile web app. After LinkedIn sign-in we redirect back here.
    frontend_url: str = field(default_factory=lambda: _env("FRONTEND_URL", "http://localhost:5173"))
    # Comma-separated origins allowed to call the API from a browser.
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        )
    )

    # --- LinkedIn (official "Sign In with LinkedIn using OpenID Connect") --
    linkedin_client_id: str = field(default_factory=lambda: _env("LINKEDIN_CLIENT_ID"))
    linkedin_client_secret: str = field(default_factory=lambda: _env("LINKEDIN_CLIENT_SECRET"))
    # Must exactly match a redirect URL registered in the LinkedIn developer portal.
    linkedin_redirect_uri: str = field(
        default_factory=lambda: _env(
            "LINKEDIN_REDIRECT_URI",
            # Render sets RENDER_EXTERNAL_URL to the service's public https address.
            _env("RENDER_EXTERNAL_URL", "http://localhost:8000").rstrip("/") + "/auth/linkedin/callback",
        )
    )

    # --- Shared secrets for non-user callers -----------------------------
    # Organizers use this to trigger post-event emails (header X-Admin-Key).
    admin_api_key: str = field(default_factory=lambda: _env("ADMIN_API_KEY"))
    # Bracelets (or the hotspot relay) send this with uploads (header X-Bracelet-Key).
    bracelet_api_key: str = field(default_factory=lambda: _env("BRACELET_API_KEY"))

    # --- Email -----------------------------------------------------------
    # "console" writes emails to MEDIA_DIR/outbox for local dev; "smtp" really sends.
    email_backend: str = field(default_factory=lambda: _env("EMAIL_BACKEND", "console"))
    email_from: str = field(default_factory=lambda: _env("EMAIL_FROM", "Tro <no-reply@tro.local>"))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "587")))
    smtp_username: str = field(default_factory=lambda: _env("SMTP_USERNAME"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    # True = STARTTLS on port 587 (Gmail, Outlook). Port 465 always uses implicit TLS.
    smtp_starttls: bool = field(default_factory=lambda: _env("SMTP_STARTTLS", "true").lower() == "true")
    # EMAIL_BACKEND=apps_script: a Google Apps Script web app that sends from
    # your Gmail over https (deploy/email-relay.gs). For hosts that block SMTP.
    email_relay_url: str = field(default_factory=lambda: _env("EMAIL_RELAY_URL"))
    email_relay_key: str = field(default_factory=lambda: _env("EMAIL_RELAY_KEY"))

    # --- AI (transcription + notes) -------------------------------------
    # Any OpenAI-compatible API. The default is Groq: its free plan needs no
    # card and has both Whisper (speech to text) and Llama (summaries).
    # Get a key at console.groq.com > API Keys and set AI_API_KEY.
    ai_api_key: str = field(default_factory=lambda: _env("AI_API_KEY", _env("GROQ_API_KEY")))
    ai_base_url: str = field(default_factory=lambda: _env("AI_BASE_URL", "https://api.groq.com/openai/v1"))
    ai_transcribe_model: str = field(default_factory=lambda: _env("AI_TRANSCRIBE_MODEL", "whisper-large-v3-turbo"))
    ai_chat_model: str = field(default_factory=lambda: _env("AI_CHAT_MODEL", "llama-3.3-70b-versatile"))

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key)

    @property
    def linkedin_configured(self) -> bool:
        return bool(self.linkedin_client_id and self.linkedin_client_secret)


def load_settings() -> Settings:
    """Build settings from the current environment variables."""
    return Settings()

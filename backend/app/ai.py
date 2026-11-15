"""The two AI calls trO makes: speech to text, and JSON-producing chat.

Any OpenAI-compatible API works. The default is Groq, whose free plan needs
no card and serves both Whisper (transcription) and Llama (notes). Set
AI_API_KEY; see config.py for the model and URL settings.

Tests replace the client with a fake via ``app.state.ai_factory`` so the
suite never calls the network.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional, Protocol

import httpx

from .config import Settings

log = logging.getLogger("tro.ai")

# Groq's free plan accepts files up to 25 MB. 16 kHz 16-bit mono WAV is
# about 1.9 MB a minute, so a clip has to be over 12 minutes to need splitting.
MAX_AUDIO_BYTES = 24 * 1024 * 1024


class AIError(Exception):
    """The AI service failed or isn't configured. The work is retried later."""


class AIClient(Protocol):
    def transcribe(self, audio: bytes, filename: str, content_type: str) -> list[dict]:
        """Return segments: [{"start": seconds, "end": seconds, "text": "..."}]."""
        ...

    def chat_json(self, system: str, user: str) -> dict:
        """Ask the chat model for a JSON object and return it parsed."""
        ...


class OpenAICompatibleClient:
    """Talks to Groq (or any OpenAI-compatible API) over plain HTTPS."""

    def __init__(self, settings: Settings, http: Optional[httpx.Client] = None):
        if not settings.ai_configured:
            raise AIError("AI_API_KEY isn't set, so recordings can't be transcribed yet")
        self.settings = settings
        self.base = settings.ai_base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=120)
        self.headers = {"Authorization": f"Bearer {settings.ai_api_key}"}

    def _post(self, path: str, **kwargs) -> dict:
        # Free plans rate-limit by the minute: wait and retry a couple of times.
        for attempt in range(3):
            try:
                resp = self.http.post(f"{self.base}{path}", headers=self.headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise AIError(f"AI service unreachable: {exc}") from exc
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == 2:
                    break
                wait = resp.headers.get("retry-after")
                time.sleep(min(float(wait), 20) if wait and wait.replace(".", "", 1).isdigit() else 3 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                # Never log the request (it carries the key); the body is the service's error message.
                raise AIError(f"AI service error {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise AIError(f"AI service busy (HTTP {resp.status_code}); will retry later")

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> list[dict]:
        if len(audio) > MAX_AUDIO_BYTES:
            raise AIError("audio is over 24 MB; split it before transcribing")
        body = self._post(
            "/audio/transcriptions",
            files={"file": (filename, audio, content_type)},
            data={
                "model": self.settings.ai_transcribe_model,
                "response_format": "verbose_json",
                "language": "en",
                "temperature": "0",
            },
        )
        segments = body.get("segments") or []
        out = [
            {"start": float(s.get("start", 0)), "end": float(s.get("end", 0)), "text": str(s.get("text", "")).strip()}
            for s in segments
            if str(s.get("text", "")).strip()
        ]
        if not out and str(body.get("text", "")).strip():
            out = [{"start": 0.0, "end": float(body.get("duration") or 0), "text": body["text"].strip()}]
        return out

    def chat_json(self, system: str, user: str) -> dict:
        body = self._post(
            "/chat/completions",
            json={
                "model": self.settings.ai_chat_model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        try:
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIError("AI answer wasn't valid JSON") from exc
        if not isinstance(parsed, dict):
            raise AIError("AI answer wasn't a JSON object")
        return parsed


def make_client(settings: Settings) -> AIClient:
    """The real client. Raises AIError if no key is configured."""
    return OpenAICompatibleClient(settings)

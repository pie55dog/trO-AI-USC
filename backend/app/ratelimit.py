"""Small in-memory rate limits for the endpoints worth abusing.

Every audio clip costs an AI transcription and a chat call, and sign-up
creates accounts, so each has a ceiling per person (or per network address
when nobody is signed in). One server process holds the counters, which is
what the free deployment runs; a bigger deployment would move this to Redis.

    limit = RateLimit("phone_upload", per_minute=12)
    limit.check(f"user:{user.id}")   # raises 429 when over
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_all: list["RateLimit"] = []


class RateLimit:
    def __init__(self, name: str, per_minute: int, per_hour: int | None = None):
        self.name = name
        self.windows = [(60.0, per_minute)] + ([(3600.0, per_hour)] if per_hour else [])
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        _all.append(self)

    def check(self, key: str) -> None:
        now = time.monotonic()
        longest = max(w for w, _ in self.windows)
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > longest:
                hits.popleft()
            for window, limit in self.windows:
                if sum(1 for t in hits if now - t <= window) >= limit:
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "too many requests; wait a minute and try again",
                        headers={"Retry-After": str(int(window if window < 120 else 60))},
                    )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request) -> str:
    # uvicorn runs with --proxy-headers on Render, so this is the caller, not the proxy.
    return request.client.host if request.client else "unknown"


def reset_all() -> None:
    """Tests start each case with empty counters."""
    for limit in _all:
        limit.reset()


# Audio: a 3-minute conversation is one clip, so a dozen a minute is far above real use.
PHONE_UPLOADS = RateLimit("phone_upload", per_minute=12, per_hour=200)
BRACELET_UPLOADS = RateLimit("bracelet_upload", per_minute=12, per_hour=200)
# Accounts: a whole event can share one campus network address, so this is generous;
# it stops scripted account creation, not a busy check-in line.
SIGN_UPS = RateLimit("sign_up", per_minute=60, per_hour=1000)
# Self-serve emails go through a Gmail relay with a daily cap.
TEST_EMAILS = RateLimit("test_email", per_minute=2, per_hour=10)
# Watch pairing codes are 6 digits: cap guesses per address so they can't be brute-forced
# in the 5 minutes a code lives (10 a minute = 50 tries of a million).
WATCH_CODE_TRIES = RateLimit("watch_code", per_minute=10, per_hour=60)
WATCH_CODES_ISSUED = RateLimit("watch_code_issue", per_minute=5, per_hour=30)

# Tro backend

FastAPI + SQLite API for Tro, the networking bracelet for Trojans. This first
version covers **onboarding** (LinkedIn sign-in, profile, preferences, bracelet
assignment), **receiving bracelet data** (stored only), and **the post-event
email** (who you met, without AI summaries yet).

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill it in
uvicorn app.main:app --reload --env-file .env
```

Open http://localhost:8000/docs for interactive API docs you can click through.

Run the tests: `pytest` (from `backend/`). They use a temporary database, a fake
LinkedIn, and a fake mail server, so they need no keys or network.

## Hosting

The demo backend runs on Google Cloud Run for $0. See [deploy/README.md](../deploy/README.md).

## What LinkedIn sign-in gives us

We use LinkedIn's official **Sign In with LinkedIn using OpenID Connect**
(scopes `openid profile email`), with no third-party services. LinkedIn returns
only: **name, profile picture, and email** (plus an id and locale).

**Bio/"About", headline and current position are not available** through any
self-serve LinkedIn product; they need partner-only APIs. So sign-in autofills
name, email and the headshot, and the user types school, major, bio, interests
and company during onboarding.

We copy the headshot to our own storage at sign-in because LinkedIn's picture
URLs are signed and expire.

Setup: in the [LinkedIn developer portal](https://www.linkedin.com/developers/apps),
create an app, add the product "Sign In with LinkedIn using OpenID Connect",
and add `LINKEDIN_REDIRECT_URI` under Auth → Authorized redirect URLs.

## API at a glance

| Who | Endpoint | What it does |
|---|---|---|
| anyone | `GET /auth/linkedin/login` | Starts LinkedIn sign-in (open this in the phone browser) |
| anyone | `GET /auth/linkedin/callback` | LinkedIn returns here; we redirect to `FRONTEND_URL/auth/callback#token=…&new_user=1` |
| anyone | `POST /users` | Sign up without LinkedIn (name + email); returns a login token |
| attendee | `GET /users/me` | Profile, preferences, and `onboarding.missing` (which screens are left) |
| attendee | `PATCH /users/me` | Edit profile fields (send only what changed) |
| attendee | `PUT /users/me/preferences` | Recording consent and recommendations (both required true/false), email opt-in, which contact fields to share |
| attendee | `POST /users/me/photo` | Upload a headshot (JPEG/PNG/WebP, ≤5 MB) |
| attendee | `DELETE /users/me` | Delete account, photo, and any bracelet audio |
| attendee | `POST /events/{id}/bracelet` | Claim a bracelet by its ESP32 id (needs onboarding complete) |
| attendee | `GET /events/{id}/bracelet` | Which bracelet I have |
| attendee | `GET /events/{id}/connections` | Who I tapped at this event (shared contact fields, recorded or contact-only) |
| anyone | `GET /events`, `GET /events/{id}` | List / view events |
| organizer | `POST /events` | Create an event |
| attendee | `POST /events/{id}/test-email` | Email me my summary for this event right now (for demos; doesn't count as the post-event email) |
| organizer | `POST /events/{id}/send-summaries` | Send every attendee their post-event email (re-runs skip people already emailed) |
| organizer | `POST /admin/email/test` | Send a test email to check SMTP |
| bracelet | `POST /bracelets/uploads` | End-of-event upload: `bracelet_id`, `event_id` (required once a bracelet is reused), `payload` (JSON text), `files` |

Auth: attendees send `Authorization: Bearer <token>` (from the sign-in
redirect). Organizers send `X-Admin-Key`, bracelets send `X-Bracelet-Key`.
If a key isn't configured, its endpoints are disabled rather than left open.

`photo_url` values are paths on the API (e.g. `/media/photos/…`); the web app
should prefix them with the API's base URL.

## Onboarding rules

Required before claiming a bracelet (spec section 5): name, email, school,
major, bio, at least one interest, and **explicit** answers to recording
consent and recommendations. Consent has no default; it stays `null` until the user picks yes or
no, and we record when the answer last changed.

## Email

`EMAIL_BACKEND=console` saves emails as `.eml` files in `media/outbox/` (open
them in any mail app). `EMAIL_BACKEND=smtp` sends through any SMTP account using
Python's standard library, e.g. Gmail with an app password (see `.env.example`).

Each attendee of an event (anyone with a bracelet assigned for it) gets one
email listing the people they connected with, showing only the contact fields
each person chose to share. Every send is logged so nobody gets duplicates.

## Not built yet (on purpose)

- **Anything that talks to the bracelet directly.** Firmware lives in the
  hardware repo. `POST /bracelets/uploads` stores whatever a bracelet sends
  with status `received`; `app/bracelets.py:process_upload` is an empty
  placeholder for turning that into connections.
- **AI**: transcription, conversation summaries, voice-note sorting, follow-up
  suggestions. The email template already has slots for them
  (`ConnectionEntry.summary`, `notes`, `follow_ups` in `app/mailer.py`).
- Deleting audio after the email is sent (comes with processing).

## Layout

```
app/
  main.py         uvicorn entry point
  factory.py      builds the app (settings, database, routers)
  config.py       environment variables
  models.py       database tables
  schemas.py      request/response shapes and validation
  security.py     login tokens, admin and bracelet keys
  linkedin.py     LinkedIn OpenID Connect client
  storage.py      photos and uploaded files on disk
  mailer.py       email backends and the post-event email template
  post_event.py   sends an event's emails
  bracelets.py    bracelet id format + processing placeholder
  routers/        HTTP endpoints, one file per area
tests/            pytest suite
```

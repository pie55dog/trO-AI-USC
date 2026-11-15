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

The demo backend runs on Render's free plan with a free Postgres database (`render.yaml`). See [deploy/README.md](../deploy/README.md). Locally it still uses SQLite.

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
| attendee | `GET /events/{id}/connections` | Who I tapped at this event (shared contact fields, recorded or contact-only, `notes` preview, `connection_id`, `both_consented`) |
| attendee | `POST /events/{id}/recordings` | Phone mic (until bracelets have mics): one 16 kHz WAV clip as the raw body (`?kind=conversation\|voice_note&connection_id&started_at`). Same consent check and AI pipeline as bracelet clips. WAV only, ≤200 s (conversation) / 40 s (voice note), 3 clips per conversation, 12 uploads a minute per person |
| attendee | `GET /events/{id}/notes` | All my notes for the event: per person, plus voice notes sorted as ideas / to-dos |
| attendee | `GET /events/{id}/notes/{user_id}` | My notes on one person: AI summary, promises, follow-ups, my voice notes, who-said-what transcript |
| attendee | `PATCH /events/{id}/voice-notes/{note_id}` | Move a voice note to another person (`person_user_id`) or category (`idea`/`task`/`other`) |
| organizer | `POST /admin/process` | Finish recordings still waiting (e.g. right after adding `AI_API_KEY`) |
| anyone | `GET /events`, `GET /events/{id}` | List / view events |
| organizer | `POST /events` | Create an event |
| attendee | `POST /events/{id}/test-email` | Email me my summary for this event right now (for demos; doesn't count as the post-event email) |
| organizer | `POST /events/{id}/send-summaries` | Send every attendee their post-event email (re-runs skip people already emailed) |
| organizer | `POST /admin/email/test` | Send a test email to check SMTP |
| bracelet | `GET /bracelets/{id}/status` | Has anyone claimed this bracelet yet? (`linked`, `event_id`, `first_name`). Polled at boot |
| bracelet | `POST /bracelets/tap` | Live tap: `{"device", "peer", "rssi"}`. Answers `waiting` until the other bracelet reports the same tap, then `paired` with `peer_name` and `match_pct`. 409 = not linked. `peer: ""` is a manual (button) tap |
| bracelet | `POST /bracelets/star` | `{"device"}`: star the wearer's latest connection (shown on the dashboard and in the email) |
| bracelet | `POST /bracelets/recordings` | Mic build: one audio clip as the raw body (`?device&kind=conversation\|voice_note&connection_id&started_at`). 403 unless both people consent. Transcribed and turned into notes in the background |
| organizer | `GET /admin/check` | Confirm an organizer key works (the organizer console signs in with it) |
| organizer | `PATCH /events/{id}` | Edit an event's name, location or start time |
| organizer | `GET /events/{id}/overview` | Counts: attendees, recording consent, email opt-in, connections, uploads, emails sent/failed |
| organizer | `GET /events/{id}/attendees` | Everyone holding a bracelet, with consent, tap count and email status |
| organizer | `POST /events/{id}/attendees` | Check-in desk: link a bracelet to an attendee by the email on their trO profile |
| organizer | `DELETE /events/{id}/attendees/{user_id}` | Take a bracelet back so it can go to someone else |
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

## Conversation notes (the AI)

Bracelet audio (or phone mic audio, see below) becomes notes in `app/recordings.py`:

1. **Consent.** A conversation clip is only accepted if *both* people currently say yes to
   recording (checked again on upload, so turning it off mid-event works). Otherwise 403 and
   nothing is kept.
2. **Speech to text.** Whisper (`whisper-large-v3-turbo` on Groq) transcribes one of the two
   bracelets' clips into timed segments.
3. **Who said what** (`app/speakers.py`). Each person is ~10-15 dB louder on their own bracelet.
   We line the two clips up by cross-correlating their loudness, then credit each segment to
   whoever's bracelet heard it louder. With one clip, the loud voice is the wearer. Anything
   unclear goes to the chat model as "?" to decide from context; it can't overrule a measured line.
4. **Per-person notes** (`app/notes_ai.py`). One chat call writes both people's notes (summary,
   topics, facts about the other person, promises, follow-ups). Every promise must quote the
   transcript word for word and is re-credited to whoever actually said that line, or it's dropped.
5. **Voice notes** are transcribed and sorted to a person, idea, task or other. Saying someone's
   name beats the model's guess; the model can only pick people you actually tapped.
6. **Privacy.** Audio is deleted right after it's transcribed and measured. Transcripts and loudness
   data are deleted once the summary emails go out. The notes stay.
7. **Prompt injection.** Transcripts and profile text are flattened and fenced before they reach the
   model, answers are parsed only as JSON into capped fields, and links or emails the model writes
   are dropped unless someone actually said them. See [`../SECURITY.md`](../SECURITY.md).

**Phone mic.** Until the bracelets have mics, the attendee's phone records instead
(`frontend/src/screens/PhoneMic.tsx`). The bracelet still does the tap; the phone polls
`/events/{id}/connections`, and when a new connection appears with `both_consented`, it records
(with a few seconds of pre-roll) until the next tap, *End conversation*, or 3 minutes, then uploads
a 16 kHz WAV to `POST /events/{id}/recordings`. Clips are stored with `bracelet_id = "PHONE"` and go
through the exact same consent check, transcription, who-said-what and notes. Two phones, or one
phone and one mic bracelet, work together the same way two bracelets do.

Set `AI_API_KEY` to a free Groq key (console.groq.com, no card). Without it, recordings are stored
with status `waiting_for_ai` and processed later by `POST /admin/process` (also run automatically
before `send-summaries`). `AI_BASE_URL` / `AI_*_MODEL` switch to any OpenAI-compatible service.

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
  bracelets.py    bracelet id format + upload processing placeholder
  recordings.py   audio in -> transcript -> notes; consent check, retries, deletion
  speakers.py     who said what, from the two bracelets' loudness
  notes_ai.py     the prompts + checks for conversation notes and voice-note sorting
  ai.py           Groq / OpenAI-compatible client (Whisper + chat)
  notes.py        reading notes back for the app and the email
  taps.py         live taps: pairs two bracelets' reports into a Connection, stars, match %
  routers/        HTTP endpoints, one file per area
tests/            pytest suite
```

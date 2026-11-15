# Security and privacy in trO

trO records real conversations between students and sends what it hears to an AI, so security is
built into the design, not added afterwards. This page covers what's protected and how, with links
to the code and the tests that check it.

## Recordings and consent

- **Both people must opt in.** A conversation is only recorded if both people said yes to recording
  when they signed up. The server checks this again when each clip arrives (`recordings.both_consent`),
  so turning recording off mid-event takes effect right away. If either person said no, the server
  answers 403 and saves nothing. The bracelet blinks the whole time it records.
- **Audio is short-lived.** Each clip is deleted as soon as it's transcribed and measured. Transcripts
  and loudness data are deleted once the summary emails go out (`recordings.purge_event`). Only the
  notes stay, and each person sees only their own.
- **Delete everything.** `DELETE /users/me` removes the account, photo, recordings, transcripts and
  notes, including clips from conversations the person was part of.
- **Contact details are opt-in per field.** People only see the fields someone chose to share
  (`connections.shared_contact`). The same rule applies to the summary email.

## Using AI safely and accurately (`backend/app/notes_ai.py`)

| Risk | What trO does |
|---|---|
| **Prompt injection by voice** ("ignore your instructions and…") | Each transcript line is flattened to one line, angle brackets are neutralized, and the transcript is fenced in `<transcript>…</transcript>`. A speaker can't fake a speaker label, close the fence or start a new section. The system prompt says the text inside is data, never instructions. |
| **Prompt injection through profiles** (a malicious name or headline) | Names and headlines are length-capped and sent as JSON values, not free text. |
| **AI writes phishing links into notes or emails** | Links and email addresses in the model's answer are removed unless someone actually said them (`_drop_unsaid_links`). |
| **Made-up promises** | Every promise must quote the transcript word for word (fuzzy-matched at 85% or better). It's credited to whoever's microphone measured that line, not to whoever the model guessed. Anything without evidence is dropped. |
| **Wrong speaker** | Who said what comes from signal processing (which device heard each line louder), not from the model. The model only fills in lines that couldn't be measured, and it can't overrule a measured one. |
| **Notes filed under a stranger** | When sorting a voice note, the model can only pick people the wearer actually tapped. If the wearer says a name out loud, that wins over the model's guess. |
| **Malformed or oversized answers** | The model's answer is parsed only as JSON into fixed fields with type checks and length caps. Nothing it returns is executed or rendered as HTML. |
| **Runaway AI cost or abuse** | Uploads are rate-limited per person and per bracelet. Phone clips must be real WAV audio no longer than the phone ever records, with at most 3 clips per conversation. Anything else is refused before it reaches the AI. |
| **Leaking the AI key** | The key lives only in the server's environment. The browser and bracelets never see it, and AI requests are never logged. |

## Accounts and access

- **Login tokens** are signed with `SECRET_KEY` (itsdangerous) and expire after 30 days. Bumping an
  account's `session_version` signs it out everywhere. A deployed server refuses to start with the
  public dev secret (`factory.create_app`).
- **Three kinds of caller**, each checked by a FastAPI dependency (`security.py`): attendees (Bearer
  token), organizers (`X-Admin-Key`) and bracelets (`X-Bracelet-Key`). Keys are compared in
  constant time. A missing key disables its endpoints instead of leaving them open.
- **LinkedIn sign-in** uses a random `state` value stored in a signed, httpOnly cookie to stop
  login CSRF.
- **Email sign-up** refuses an email that already has an account. Because ownership isn't verified
  there, it never signs anyone in to an existing account. Sign-ups are rate-limited per network
  address.
- **Authorization is per object.** You can only read your own notes. A clip can only be attached to
  a conversation you were in, at that event.

## Web app and API hardening

- **Content-Security-Policy** on the production web app: scripts only from the site itself, network
  calls only to the site and the trO API, no plugins and no `<base>` tag. This blocks the usual
  ways an injected script would run or steal a login token (`frontend/vite.config.ts`).
- **API response headers:** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `default-src 'none'`, plus HSTS over https.
- **CORS** allows only the app's own origins.
- **Links from profiles** are only rendered when they're `http(s)` web links, both in the app and in
  emails. All user text in emails is HTML-escaped. React escapes everything on screen, and no code
  injects raw HTML.
- **Uploads:** photos are checked by their file signature, not their name. Stored file paths are
  resolved inside the media folder, so nothing can write outside it. Upload sizes are capped.
- **Database:** Render Postgres with no public access (`ipAllowList: []`). Secrets are only in
  Render's environment, never in the repo.

## Tests

`backend/tests/test_security.py`, `test_phone_mic.py` and `test_recordings.py` cover: rate limits,
non-audio and over-long uploads, the per-conversation clip cap, consent refusals, security headers,
refusing the dev secret, fake speaker labels and fence-breaking in transcripts, stripping invented
links, and voice notes trying to pick strangers. Run them with `cd backend && pytest`.

## Known limits and next steps

- **One bracelet key for every bracelet.** Someone who pulled the key out of a bracelet's firmware
  could fake taps. Next step: a key per device, issued when the bracelet is claimed.
- **Rate limits are kept in memory** in one server process, which matches the free deployment. A
  multi-server deployment would move them to Redis.
- **Login tokens are stored in localStorage.** The CSP and the lack of raw-HTML rendering are what
  protect them. Moving to httpOnly cookies would need the app and API on the same site.
- **Email ownership isn't verified** for non-LinkedIn sign-up. A one-time code by email would close
  this gap.

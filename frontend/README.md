# Tro web app

The mobile web app an attendee opens after tapping their bracelet. It's built
from the refined Figma frames (393px, grayscale, no branding): **Welcome to
event** (step 1, profile), **Set your preferences** (step 2, explicit
recording consent), **This is trO** (tutorial), and the **event** dashboard.

React + TypeScript + Vite + Tailwind, with Lucide icons.

## Run it

Start the backend first (see `../backend/README.md`), then:

```bash
cd frontend
npm install
cp .env.example .env      # VITE_API_URL=http://localhost:8000
npm run dev               # http://localhost:5173
```

Open `http://localhost:5173/e/<eventId>?b=<braceletId>`. That's the link a
bracelet tap should open. For example, create an event with
`curl -X POST localhost:8000/events -H "X-Admin-Key: …" -H "content-type: application/json" -d '{"name":"Industry Night"}'`
and then open `/e/1?b=A4CF0042`.

To try it on a phone, put the phone on the same Wi-Fi or hotspot as your laptop. Set
`VITE_API_URL` to `http://<laptop-ip>:8000`, add `http://<laptop-ip>:5173` to the backend's
`CORS_ORIGINS` and `FRONTEND_URL`, then open `http://<laptop-ip>:5173/e/1` on the phone.

Tests: `npm test`. Production build: `npm run build`.

## Test on a phone (GitHub Pages)

Every push to `main` that touches `frontend/` deploys the app to
`https://pie55dog.github.io/trO-AI-USC/` (workflow: `.github/workflows/pages.yml`).

- One-time setup: repo Settings > Pages > Source: **GitHub Actions**.
- With no `VITE_API_URL`, the deployed app runs in **preview mode** (`src/preview.ts`):
  the whole flow works, but what you enter stays on that phone. It never shows
  made-up events or connections, so the dashboard shows its empty states and
  LinkedIn sign-in is hidden.
- Pages only hosts static files, so for real accounts the backend has to run somewhere else.
  Set the repo variable `VITE_API_URL` (Settings > Secrets and variables >
  Actions > Variables) to its **HTTPS** URL and re-run the workflow. A laptop
  backend works through a tunnel such as `cloudflared tunnel --url http://localhost:8000`.
- On that backend, set `CORS_ORIGINS=https://pie55dog.github.io` and
  `FRONTEND_URL=https://pie55dog.github.io/trO-AI-USC`.
- A tap link looks like `https://pie55dog.github.io/trO-AI-USC/e/1?b=ABC123`.

## Flow

1. **Welcome** (`/e/:id/welcome`). The user enters the email the summary goes to, then their profile: name, school,
   major, an optional bio (up to 20 words), an optional position, interests, links and a photo. **Continue**
   creates the account from name and email. The form is saved as a draft, so a reload never loses what the user
   typed.
2. **Preferences** (`/e/:id/preferences`). Recording consent and recommendations both start unanswered. Finish
   is disabled until both are picked. Finishing links the tapped bracelet to the attendee.
3. **Tutorial** (`/e/:id/tutorial`). The gray circles are placeholders for the 3D animations. Each has a
   `data-animation` attribute (`tap-a`, `tap-b`, `recording-light`, `voice-note`) to swap it out.
4. **Dashboard** (`/e/:id`). The user's connections, with only the contact info each person chose to share.
   It also says whether each conversation was recorded (both people consented) or contact only.

## Organizer console

`/organizer` (e.g. `https://pie55dog.github.io/trO-AI-USC/organizer`) is for event planners. Sign in with the
server's `ADMIN_API_KEY`; it's kept in this browser until **Sign out**. It's built for a laptop at the check-in
desk but works on a phone.

- **New event**: name, place and start time.
- **Registration**: the attendee link with a downloadable QR code, a generator for each bracelet's tap link (to
  write to its NFC tag), and a check-in desk form that links a bracelet to someone by their profile email.
- **Attendees**: everyone holding a bracelet, with recording consent, taps and email status. Search, export CSV,
  and take a bracelet back so it can go to someone else. Refreshes every 15 seconds.
- **After the event**: send the summary emails (asks first, safe to re-run) and send a test email.
- **Details**: edit the name, place and time.

It needs a backend, so a preview build (no `VITE_API_URL`) only shows the sign-in page with a note.

## Differences from Figma, on purpose

- "event" shows the real event name once it loads, and falls back to "event".
- The dashboard has no **match %**, and it has no phone chip or tappable conversation notes. Those need the
  AI and matching steps that aren't built yet, so the app doesn't show made-up values.
- The **Recommendations** tab shows an empty state until recommendations exist.
- Icons are Lucide equivalents of the Figma icons. The Figma asset download was blocked in the build environment.

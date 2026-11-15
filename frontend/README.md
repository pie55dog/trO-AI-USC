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

## Flow

1. **Welcome** (`/e/:id/welcome`). The user enters the email the summary goes to, then their profile: name, school,
   major, a 5–20 word bio, an optional position, interests, links and a photo. **Pull from LinkedIn** signs in
   with LinkedIn and fills in their name, email and photo. Without LinkedIn, **Continue** creates the account from
   name and email. The form is saved as a draft, so the LinkedIn redirect never loses what the user typed.
2. **Preferences** (`/e/:id/preferences`). Recording consent and recommendations both start unanswered. Finish
   is disabled until both are picked. Finishing links the tapped bracelet to the attendee.
3. **Tutorial** (`/e/:id/tutorial`). The gray circles are placeholders for the 3D animations. Each has a
   `data-animation` attribute (`tap-a`, `tap-b`, `recording-light`, `voice-note`) to swap it out.
4. **Dashboard** (`/e/:id`). The user's connections, with only the contact info each person chose to share.
   It also says whether each conversation was recorded (both people consented) or contact only.

## Differences from Figma, on purpose

- "event" shows the real event name once it loads, and falls back to "event".
- The dashboard has no **match %**, and it has no phone chip or tappable conversation notes. Those need the
  AI and matching steps that aren't built yet, so the app doesn't show made-up values.
- The **Recommendations** tab shows an empty state until recommendations exist.
- Icons are Lucide equivalents of the Figma icons. The Figma asset download was blocked in the build environment.

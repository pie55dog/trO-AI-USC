# trO-AI-USC

Tro: a networking bracelet for Trojans. Tap bracelets to connect, keep your phone in your pocket, and get one email the next morning with everyone you met.

- [`backend/`](backend/README.md): FastAPI API (LinkedIn sign-in, onboarding, bracelet assignment and uploads, post-event email)
- [`frontend/`](frontend/README.md): mobile web app (sign-up, preferences, tutorial, event dashboard)

## Test on a phone with the real backend

Run everything on a laptop and open it from a phone on the same Wi-Fi:

```
./scripts/local-server.sh      # prints the link to open on the phone
./scripts/send-summaries.sh    # sends the summary email to everyone who signed up
```

The first run creates `backend/.env`. Emails are saved to `backend/media/outbox`
until you fill in the `SMTP_*` lines there (a Gmail app password works) and set
`EMAIL_BACKEND=smtp`, then restart the script.


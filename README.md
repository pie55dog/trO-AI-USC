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
until you run `./scripts/setup-email.sh`. It asks for the address you want trO to
send from and an app password (typed in Terminal, never into a chat), tests the
login, saves it to `backend/.env`, and sends a confirmation email. Then restart
the server.


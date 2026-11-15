# trO for Apple Watch

The watch is the microphone while the bracelets do the taps, so nobody has to keep a phone screen
on. It follows the same rules as the bracelet mic and the phone mic page:

| What happens | Watch |
|---|---|
| You tap bracelets and you both said yes to recording | A tap on the wrist; it records (with 6 s of audio from just before it noticed the tap) |
| Either of you said no | A different tap on the wrist; nothing is recorded |
| Next tap, **End conversation**, or 3 minutes | The clip stops and uploads as 16 kHz WAV |
| **Voice note** | Records a note for yourself (30 s max) |

Clips go to `POST /events/{id}/recordings`, the same endpoint and AI pipeline as the phone mic
(consent checked again on the server, transcription, who-said-what, notes, email).

## Run it

1. Open `trO.xcodeproj` in **Xcode 16 or later**.
2. Simulator: pick an Apple Watch simulator and press Run. The simulator uses your Mac's mic.
3. Real watch: click the project > **trO Watch App** target > **Signing & Capabilities** and pick
   your Team (a free Apple ID works). Choose your watch as the destination and press Run. The watch
   needs Developer Mode turned on (Settings > Privacy & Security on the watch).
4. Point it at a different server in `trO Watch App/Config.swift` (`apiBase`). It defaults to the live
   `https://tro-api.onrender.com`.

## Pair the watch with your account

Typing a password on a watch is miserable, so pairing uses a one-time code:

1. On your phone, open the trO dashboard > **Phone mic** > **Get watch code**.
2. Type the 6 digits on the watch. Done: it remembers you for that event.

How the code is kept secure (`backend/app/routers/watch.py`):

- Codes last 5 minutes and work once. Asking for a new one cancels the old one.
- The server stores only a keyed hash of each code, never the code itself.
- Guesses are rate-limited per network address (10 a minute).
- The watch keeps its login in the **Keychain**, readable only on that watch and never backed up.
  "Unpair watch" deletes it, and deleting your account revokes it.

## Files

| File | What it does |
|---|---|
| `MicController.swift` | Watches for new taps, starts and stops clips, uploads with retries |
| `Audio.swift` | Microphone → 16 kHz mono 16-bit, a rolling buffer, WAV encoding |
| `API.swift` | Backend calls, and the Keychain storage for the pairing |
| `Views.swift` | Pairing keypad and the recording screen |
| `Config.swift` | Server address, time limits, pre-roll |

## Limits

- watchOS only lets the mic **start** while the app is on screen. Once it's listening, the background
  audio mode keeps it going with your wrist down.
- The watch checks for new taps every 2.5 s. That's why each clip includes a few seconds from
  before the tap was noticed.
- This is a watch-only app (no iPhone app). To ship it on the App Store, add Xcode's watch-only
  container target.

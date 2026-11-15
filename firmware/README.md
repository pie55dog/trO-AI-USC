# trO bracelet firmware

Runs on a **Seeed XIAO ESP32-S3** with 3 LEDs, a button and a battery (no mic in this build).
Hold two bracelets together for half a second and both people show up on each other's
dashboard, live, and in the next-morning email.

```
 bracelet A ──ESP-NOW beacons──► bracelet B      (each hears the other's id + signal strength)
     │  "I'm touching B"              │  "I'm touching A"
     └──────► POST /bracelets/tap ◄───┘          (trO backend pairs the two matching reports)
                     │
             Connection created ──► phone dashboard (refreshes every 4 s) + summary email
```

## Parts and wiring

| Part | XIAO pin |
|---|---|
| LED1 (ready / breathing) | D10 → 220 Ω → LED → GND |
| LED2 | D9 → 220 Ω → LED → GND |
| LED3 | D8 → 220 Ω → LED → GND |
| Button | D1 and GND (uses the internal pull-up) |
| Battery | BAT+ / BAT− pads |
| Antenna | Clip the U.FL antenna on, or the RSSI readings are useless |

Pins are in `trO_bracelet/config.h`. **Check the button pin:** the original sketch's comment said
D3 but its code used D1, so this keeps D1. Change `PIN_BUTTON` if yours is on D3.

## NFC sticker (yes, add one)

The phone app already expects it: tapping a phone to the bracelet opens
`https://pie55dog.github.io/trO-AI-USC/e/<event>?b=<bracelet id>`, which walks a new person through
sign-up and links that bracelet to them. Without a sticker, staff have to type bracelet ids.

- Any **NTAG213/215/216** sticker works (passive, no wiring, no battery). Stick it on the band.
- The sketch prints the exact link at boot: `NFC sticker URL: ...`. Set `NFC_EVENT_ID` in
  `config.h` to the event's id first.
- Write it with the free **NFC Tools** app: *Write > Add a record > URL*, then tap the sticker.
- iPhones read NFC URL stickers with no app; Android needs NFC turned on.
- New event, same bracelets? Rewrite the stickers with the new event id (they're rewritable).

The ESP32-S3 has no NFC radio, so the sticker is only for the phone. Bracelet-to-bracelet taps use
ESP-NOW.

## Flash it (Arduino IDE)

1. **Boards Manager:** install *esp32 by Espressif Systems*, version **3.x**. Pick board **XIAO_ESP32S3**.
2. **Library Manager:** install **ArduinoJson** (v7).
3. Copy `trO_bracelet/secrets.example.h` to `trO_bracelet/secrets.h` and fill in:
   - `WIFI_SSID` / `WIFI_PASS`: a phone hotspot. **All bracelets must be on the same network**, since
     ESP-NOW only works on one WiFi channel. On iPhone turn on *Maximize Compatibility* (2.4 GHz).
   - `SERVER_URL`: `https://tro-api.onrender.com`, or `http://<laptop IP>:8000` if you run
     `./scripts/local-server.sh` on a laptop joined to the same hotspot.
   - `BRACELET_KEY`: the backend's `BRACELET_API_KEY` (Render: *tro-api > Environment*; locally:
     `backend/.env`).
4. Open `trO_bracelet/trO_bracelet.ino` and upload. Every bracelet gets the same build: each names
   itself from its chip (`TRO-1A2B3C`, printed at boot). To force a name, set `DEVICE_ID` in `config.h`.

`secrets.h` is in `.gitignore`. Keep passwords and the key out of commits and chats.

## Calibrate the tap (2 minutes, do it once)

Open Serial Monitor at 115200. With another bracelet on, it prints the nearest one every second:

```
near TRO-4D5E6F rssi -36 (raw -35), 1 bracelet(s) in range
```

Note the number with the two bracelets **touching**, then **30 cm apart**. Set `RSSI_TOUCH` in
`config.h` between the two, a bit closer to the touching value, and re-flash. Wrists, sleeves and
which way the antennas face all move it, so test the way people will actually hold them.

## Using it

| LEDs | Meaning |
|---|---|
| LED1 breathing | Ready |
| 1-2-3 swipe every 2 s | Nobody has claimed this bracelet yet: tap a phone to the NFC sticker and sign up. It notices within ~5 s |
| LED2 fast blink | Joining WiFi |
| LED2 slow blink | Can't reach the server (or it's waking up, up to a minute) |
| LED2 solid | Tap detected, waiting for the other bracelet |
| Chase, then 1-3 LEDs | Paired! More LEDs = more in common (shared interests, major, school). Only shown if both people opted in to recommendations |
| All flash once | Starred |
| LED3 blinks 3x | This bracelet isn't linked to anyone yet |
| All flash 3x | Pairing failed (the other bracelet never reported). Just tap again |

**Button:** click = star your latest contact (★ on your dashboard and in your email). Hold 1 s =
manual tap: both people hold their buttons at the same time, for when the radio tap won't trigger.
Manual taps pair with any other manual tap at the event in the same few seconds, so do them together.

## Test without hardware

`tools/fake_bracelet.py` sends exactly what the firmware sends:

```bash
export TRO_SERVER=http://localhost:8000 TRO_BRACELET_KEY=<key>
python3 firmware/tools/fake_bracelet.py status TRO-1
python3 firmware/tools/fake_bracelet.py tap TRO-1 TRO-2   # two bracelets held together
python3 firmware/tools/fake_bracelet.py star TRO-1
```

The bracelets need to be claimed first (sign up in the phone app with `?b=TRO-1`). Tap-detection
unit tests run on a laptop: `firmware/test/run_host_tests.sh`.

## What changed from the original ESP-NOW sketch

Same idea, same LEDs and button, but:

- **Talks to the trO backend** (`/bracelets/tap`, `/bracelets/star`) instead of a separate laptop
  server, so taps land on the real dashboards and in the email. HTTPS works, with the connection kept
  open between tries.
- **Tracks every nearby bracelet separately** (`TapDetector.h`). The old one kept only the last beacon
  heard, so in a room with a third bracelet the readings flip between people and the hold timer keeps
  resetting.
- **Keeps beaconing while it talks to the server.** The old loop stopped broadcasting during pairing,
  so the other bracelet could lose track of it and never report its half of the tap.
- **WiFi power save off**, which otherwise makes ESP-NOW miss most beacons.
- **Smoothed RSSI with hysteresis**, so one weak reading doesn't cancel a hold.
- Radio callback hands data to the main loop through a queue (no shared variables between tasks),
  plus button debouncing.
- Knows whether it's been claimed yet and says so with its LEDs.
- No per-board editing, and no WiFi password in the code.

## Not in this build

The mic. The backend already has the hooks for it: `/bracelets/tap` returns `both_consented` (start
the recording light only when it's true), and `POST /bracelets/uploads` accepts audio files.

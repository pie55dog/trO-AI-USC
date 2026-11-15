// trO bracelet settings you might tune. Secrets (WiFi, server key) go in
// secrets.h instead, which is never committed.
#pragma once

// ---- Identity ----------------------------------------------------------
// Leave blank and each board names itself from its chip id ("TRO-1A2B3C"),
// so every bracelet runs the exact same build. Set e.g. "TRO-1" to override.
#define DEVICE_ID ""

// ---- Pins (Seeed XIAO ESP32-S3) ------------------------------------------
//   LED pin -> 220R -> LED anode, LED cathode -> GND (x3)
//   Button: one leg to the pin, the other to GND (internal pull-up)
//   Battery on the BAT+/BAT- pads. Clip the antenna on!
#define PIN_LED1 D10
#define PIN_LED2 D9
#define PIN_LED3 D8
#define PIN_BUTTON D1  // the old sketch's comment said D3 but its code used D1; match your wiring
#define LED_ON 220     // PWM brightness for "on", 0-255

// ---- Tap detection (calibrate with the Serial Monitor) -------------------
// Open Serial Monitor at 115200 and watch the "near" line: note the RSSI
// with two bracelets touching and at 30 cm. Put RSSI_TOUCH between them,
// closer to the touching value.
#define RSSI_TOUCH (-40)
#define RSSI_RELEASE (RSSI_TOUCH - 7)  // hysteresis: one weak reading won't cancel a hold
#define TOUCH_HOLD_MS 500              // must stay touching this long
#define BEACON_MS 100                  // broadcast our id ~10x a second
// ESP-NOW/WiFi transmit power in 0.25 dBm steps (8 = 2 dBm). Low power makes
// "touching" stand out from "nearby", but it is also the power used to reach
// the WiFi hotspot, so keep the hotspot phone within a few meters. Raise it
// (e.g. 20 = 5 dBm) if WiFi keeps dropping, then re-calibrate RSSI_TOUCH.
#define TX_POWER_QDBM 8

// ---- Pairing with the server ---------------------------------------------
#define PAIR_COOLDOWN_MS 10000  // after pairing, ignore the same bracelet this long
#define RETRY_COOLDOWN_MS 3000  // after a failed pairing, let them try again soon
#define TAP_RETRY_MS 300        // re-report while waiting for the other bracelet
#define TAP_TIMEOUT_MS 6000     // give up if the other bracelet never reports
#define HOLD_PRESS_MS 1000      // button held this long = manual tap
#define DEBOUNCE_MS 30

// ---- Server checks -------------------------------------------------------
#define STATUS_POLL_UNLINKED_MS 5000  // until someone claims the bracelet
#define STATUS_POLL_LINKED_MS 60000   // afterwards (catches a re-assignment)
#define HTTP_TIMEOUT_MS 4000
#define WAKE_TIMEOUT_MS 70000  // a sleeping free Render server takes up to a minute

// ---- NFC sticker ---------------------------------------------------------
// The phone app opens from <APP_URL>/e/<event>?b=<bracelet id>. The sketch
// prints the exact link at boot: write it to an NTAG213/215 sticker on the
// bracelet (NFC Tools app > Write > Add a record > URL).
#define APP_URL "https://pie55dog.github.io/trO-AI-USC"
#define NFC_EVENT_ID 1  // the event id the organizer created (POST /events)

// ---- Microphone (conversation notes + voice notes) -----------------------
// 0 = no-mic build (taps and stars only). Set to 1 once a mic is attached;
// nothing else in the sketch needs to change. Needs PSRAM: Arduino IDE >
// Tools > PSRAM > "OPI PSRAM".
#define MIC_ENABLED 0

#define MIC_TYPE_PDM 1  // XIAO ESP32-S3 Sense board's built-in mic (no wiring)
#define MIC_TYPE_I2S 2  // an I2S MEMS mic such as the INMP441
#define MIC_TYPE MIC_TYPE_PDM

// Sense board built-in mic (fixed by the board).
#define PIN_MIC_CLK 42
#define PIN_MIC_DATA 41
// I2S mic wiring (INMP441: SCK, WS, SD; L/R to GND; VDD to 3V3).
#define PIN_MIC_BCLK D2
#define PIN_MIC_WS D3
#define PIN_MIC_SD D4

#define MIC_GAIN_SHIFT 2       // digital gain: each step doubles the volume. Lower it if speech clips.
#define MAX_CONVERSATION_S 180 // a conversation recording stops after 3 minutes (5.8 MB of PSRAM)
#define MAX_VOICE_NOTE_S 30
#define WALK_AWAY_MS 20000     // stop recording once the other bracelet hasn't been heard for this long
#define DOUBLE_CLICK_MS 350    // double-click the button = start a voice note
#define UPLOAD_TIMEOUT_MS 65000

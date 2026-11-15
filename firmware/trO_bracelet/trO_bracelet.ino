// =====================================================================
// trO bracelet firmware: Seeed XIAO ESP32-S3 (mic optional: MIC_ENABLED in config.h)
//
// Every bracelet runs this exact sketch (each names itself from its chip
// id). Arduino IDE: board "XIAO_ESP32S3", esp32 core 3.x by Espressif.
// Library Manager: ArduinoJson (v7). Copy secrets.example.h to secrets.h.
//
// How a tap works:
//   * Each bracelet broadcasts its id ~10x/s over ESP-NOW and tracks the
//     signal strength (RSSI) of every other bracelet it hears.
//   * When one stays above RSSI_TOUCH for TOUCH_HOLD_MS (held together),
//     both report it to POST /bracelets/tap on the trO backend. The server
//     pairs the two matching reports into a Connection, which shows up on
//     both people's phone dashboards right away and in the next-day email.
//   * Paired: LED chase, then the match % as 1-3 LEDs.
//
// Button: click = star your latest contact (it's marked on the dashboard
// and in the email); hold 1 s = manual tap, for when the radio tap doesn't
// trigger (both people hold their buttons at the same time).
//
// Mic build (MIC_ENABLED 1):
//   * After a tap where BOTH people agreed to recording, the bracelet records
//     the conversation (LED3 blinks so everyone can see). It stops when you
//     click the button, walk apart, tap someone else, or after 3 minutes, then
//     uploads it in the background to POST /bracelets/recordings.
//   * Double-click = record a voice note (LED3 solid), click again to stop.
//     trO sorts it to the right person or idea after the event.
//
// LEDs (LED1 = D10, LED2 = D9, LED3 = D8):
//   LED1 breathing ............ ready
//   1-2-3 swipe every 2 s ..... nobody has claimed this bracelet yet: tap a phone to its NFC sticker
//   LED2 blinking fast ........ joining WiFi
//   LED2 slow blink ........... can't reach the server
//   LED2 solid ................ tap detected, talking to the server
//   chase + 1-3 LEDs .......... paired! (more LEDs = more in common)
//   all flash once ............ starred
//   LED3 blinks 3x ............ not linked yet (claim it with your phone first)
//   all flash 3x .............. pairing failed, try again
//   LED3 blinking ............. recording this conversation (mic build)
//   LED3 solid ................ recording a voice note (mic build)
// =====================================================================

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_mac.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include <time.h>

#include "Recorder.h"
#include "TapDetector.h"
#include "config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy secrets.example.h to secrets.h (same folder) and fill in your WiFi and server details."
#endif

#if !defined(ESP_ARDUINO_VERSION_MAJOR) || ESP_ARDUINO_VERSION_MAJOR < 3
#error "Needs the esp32 Arduino core 3.x (Boards Manager > esp32 by Espressif Systems)."
#endif

static const char BEACON_MAGIC[4] = {'T', 'R', 'O', '2'};

struct __attribute__((packed)) Beacon {
  char magic[4];
  char id[TRO_ID_LEN];  // NUL-terminated
};

struct Sample {
  char id[TRO_ID_LEN];
  int8_t rssi;
  uint32_t at;
};

static char deviceId[TRO_ID_LEN];
static QueueHandle_t rxQueue;
static volatile bool espNowReady = false;
static TapDetector detector;

// What the server says about this bracelet.
enum Link { LINK_UNKNOWN, LINK_NO, LINK_YES };
static Link linkState = LINK_UNKNOWN;
static bool serverReachable = false;
static int eventId = 0;
static uint32_t nextStatusAt = 0;

static WiFiClientSecure tlsClient;
static WiFiClient plainClient;

#if MIC_ENABLED
static void startConversation(int connectionId, const char* peer);  // defined in the microphone section
#endif

static const uint8_t LED_PINS[3] = {PIN_LED1, PIN_LED2, PIN_LED3};

// ================= LEDs (3 discrete LEDs, PWM) =================
static void ledsSet(uint8_t a, uint8_t b, uint8_t c) {
  analogWrite(LED_PINS[0], a);
  analogWrite(LED_PINS[1], b);
  analogWrite(LED_PINS[2], c);
}
static void ledsAll(uint8_t v) { ledsSet(v, v, v); }

static void ledsBreathe() {  // ready: LED1 breathing faintly
  uint8_t b = (uint8_t)(6 + 22 * (1 + sin(millis() / 900.0)) / 2);
  ledsSet(b, 0, 0);
}

static void ledsUnlinked() {  // "tap your phone to me": quick 1-2-3 swipe every 2 s
  uint32_t t = millis() % 2000;
  ledsSet(t < 150 ? LED_ON : 0, (t >= 150 && t < 300) ? LED_ON : 0, (t >= 300 && t < 450) ? LED_ON : 0);
}

static void ledsNoServer() {  // LED2 slow blink
  ledsSet(0, (millis() % 2000) < 400 ? 60 : 0, 0);
}

static void ledsNoWifi() {  // LED2 fast blink
  ledsSet(0, (millis() % 400) < 100 ? 40 : 0, 0);
}

static void ledsConnecting() { ledsSet(0, LED_ON, 0); }

static void ledsRecording() {  // the "trO is taking notes" light: LED3 blinking
  ledsSet(0, 0, (millis() % 1000) < 500 ? LED_ON : 0);
}

static void ledsVoiceNote() { ledsSet(0, 0, LED_ON); }

static void ledsPairSweep() {  // back-and-forth chase, 3 passes
  const uint8_t order[4] = {0, 1, 2, 1};
  for (int rep = 0; rep < 3; rep++) {
    for (int k = 0; k < 4; k++) {
      uint8_t v[3] = {0, 0, 0};
      v[order[k]] = LED_ON;
      ledsSet(v[0], v[1], v[2]);
      delay(90);
    }
  }
  ledsAll(0);
}

static void ledsMatchBar(int pct) {  // match % as 1, 2 or 3 LEDs for a few seconds
  int lit = pct >= 70 ? 3 : pct >= 45 ? 2 : 1;
  ledsSet(lit >= 1 ? LED_ON : 0, lit >= 2 ? LED_ON : 0, lit >= 3 ? LED_ON : 0);
  delay(3500);
  ledsAll(0);
}

static void ledsError() {
  for (int i = 0; i < 3; i++) {
    ledsAll(LED_ON);
    delay(120);
    ledsAll(0);
    delay(120);
  }
}

static void ledsNotLinkedFlash() {
  for (int i = 0; i < 3; i++) {
    ledsSet(0, 0, LED_ON);
    delay(250);
    ledsAll(0);
    delay(250);
  }
}

static void ledsStarred() {
  ledsAll(LED_ON);
  delay(250);
  ledsAll(0);
}

static void ledsNothingToStar() {
  for (int i = 0; i < 2; i++) {
    ledsSet(0, 0, 60);
    delay(150);
    ledsAll(0);
    delay(150);
  }
}

// ================= ESP-NOW =================
// Runs in the WiFi task: copy the beacon into a queue and get out. The
// main loop does the thinking, so nothing here races with it.
static void onEspNowRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len != (int)sizeof(Beacon)) return;
  const Beacon* b = (const Beacon*)data;
  if (memcmp(b->magic, BEACON_MAGIC, sizeof(BEACON_MAGIC)) != 0) return;
  Sample s;
  memcpy(s.id, b->id, TRO_ID_LEN);
  s.id[TRO_ID_LEN - 1] = '\0';
  if (strcmp(s.id, deviceId) == 0) return;
  s.rssi = (info && info->rx_ctrl) ? info->rx_ctrl->rssi : -127;
  s.at = millis();
  xQueueSend(rxQueue, &s, 0);  // full queue: drop this one, the next comes in 100 ms
}

// Beacons go out from their own task so they keep going while the main
// loop waits on the server. (The original sketch stopped beaconing during
// pairing, so the other bracelet could lose track and never report.)
static void beaconTask(void*) {
  Beacon b;
  memcpy(b.magic, BEACON_MAGIC, sizeof(BEACON_MAGIC));
  memset(b.id, 0, sizeof(b.id));
  strncpy(b.id, deviceId, sizeof(b.id) - 1);
  const uint8_t bcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  for (;;) {
    if (espNowReady) esp_now_send(bcast, (const uint8_t*)&b, sizeof(b));
    // A little jitter so two bracelets don't keep colliding in lockstep.
    vTaskDelay(pdMS_TO_TICKS(BEACON_MS - 10 + (esp_random() % 21)));
  }
}

static void espNowSetup() {
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }
  esp_now_register_recv_cb(onEspNowRecv);
  esp_now_peer_info_t peer = {};
  memset(peer.peer_addr, 0xFF, 6);  // broadcast
  peer.channel = 0;                 // whatever channel the WiFi is on
  peer.ifidx = WIFI_IF_STA;
  esp_now_add_peer(&peer);
  esp_wifi_set_max_tx_power(TX_POWER_QDBM);
  espNowReady = true;
}

// ================= HTTP =================
static bool useTls() { return strncmp(SERVER_URL, "https://", 8) == 0; }

// One request to the backend. Returns the HTTP status (negative = no
// connection). Keeps the connection open between calls: a fresh TLS
// handshake costs the ESP32 most of a second.
static int api(const char* method, const String& path, const JsonDocument* body, JsonDocument* out,
               uint32_t timeoutMs = HTTP_TIMEOUT_MS) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  HTTPClient http;
  http.setReuse(true);
  http.setConnectTimeout(timeoutMs);
  http.setTimeout(timeoutMs > 65000 ? 65000 : timeoutMs);
  String url = String(SERVER_URL) + path;
  bool ok = useTls() ? http.begin(tlsClient, url) : http.begin(plainClient, url);
  if (!ok) return -1;
  http.addHeader("X-Bracelet-Key", BRACELET_KEY);
  int code;
  if (body) {
    String json;
    serializeJson(*body, json);
    http.addHeader("Content-Type", "application/json");
    code = http.sendRequest(method, json);
  } else {
    code = http.sendRequest(method);
  }
  if (code > 0 && out) {
    out->clear();
    if (deserializeJson(*out, http.getString()) != DeserializationError::Ok) out->clear();
  } else if (code == 401 || code == 503) {
    Serial.println("Server refused the bracelet key: check BRACELET_KEY in secrets.h");
  }
  http.end();
  serverReachable = code > 0;
  return code;
}

static void addEvent(JsonDocument& doc) {
  if (eventId > 0) doc["event_id"] = eventId;
}

// The free Render server sleeps when idle; the first request wakes it.
static void wakeServer() {
  Serial.printf("Waking %s ...\n", SERVER_URL);
  uint32_t t0 = millis();
  while (millis() - t0 < 2 * WAKE_TIMEOUT_MS) {
    ledsNoServer();
    if (api("GET", "/health", nullptr, nullptr, WAKE_TIMEOUT_MS) == 200) {
      Serial.printf("Server awake (%lu ms)\n", (unsigned long)(millis() - t0));
      return;
    }
    delay(1000);
  }
  Serial.println("Server didn't answer; will keep trying in the background");
}

// GET /bracelets/{id}/status: has someone claimed this bracelet yet?
static void checkStatus() {
  JsonDocument resp;
  int code = api("GET", String("/bracelets/") + deviceId + "/status", nullptr, &resp);
  if (code == 200) {
    Link was = linkState;
    linkState = resp["linked"].as<bool>() ? LINK_YES : LINK_NO;
    eventId = resp["event_id"] | 0;
    if (linkState != was) {
      if (linkState == LINK_YES)
        Serial.printf("Linked: %s at event %d\n", (const char*)(resp["first_name"] | "someone"), eventId);
      else
        Serial.println("Not linked yet: tap a phone to this bracelet's NFC sticker and sign up");
    }
  }
  nextStatusAt = millis() + (linkState == LINK_YES ? STATUS_POLL_LINKED_MS : STATUS_POLL_UNLINKED_MS);
}

// ================= pairing =================
// Report the tap until the server pairs it with the other bracelet's report.
// An empty peer is a manual tap (button held).
static void tryPair(const char* peer) {
  ledsConnecting();
  Serial.printf("Tap: %s (rssi %d)\n", peer[0] ? peer : "manual", peer[0] ? detector.rssiOf(peer) : 0);
  JsonDocument req, resp;
  req["device"] = deviceId;
  req["peer"] = peer;
  if (peer[0]) req["rssi"] = detector.rssiOf(peer);
  addEvent(req);

  uint32_t t0 = millis();
  while (millis() - t0 < TAP_TIMEOUT_MS) {
    int code = api("POST", "/bracelets/tap", &req, &resp);
    if (code == 200 && strcmp(resp["status"] | "", "paired") == 0) {
      Serial.printf("Paired with %s (connection %s)\n", (const char*)(resp["peer_name"] | "?"),
                    (const char*)(resp["session"] | "?"));
      ledsPairSweep();
      if (!resp["match_pct"].isNull()) {
        int pct = resp["match_pct"].as<int>();
        Serial.printf("Match %d%%\n", pct);
        ledsMatchBar(pct);
      }
      if (peer[0]) detector.setCooldown(peer, millis(), PAIR_COOLDOWN_MS);
#if MIC_ENABLED
      // Record only if BOTH people said yes at sign-up (the server checks again on upload).
      if (resp["both_consented"].as<bool>()) startConversation(resp["connection_id"] | 0, peer);
#endif
      return;
    }
    if (code == 409) {  // nobody has claimed this bracelet yet
      linkState = LINK_NO;
      nextStatusAt = millis() + STATUS_POLL_UNLINKED_MS;
      Serial.println("Can't connect: this bracelet isn't linked to anyone yet");
      ledsNotLinkedFlash();
      if (peer[0]) detector.setCooldown(peer, millis(), RETRY_COOLDOWN_MS);
      return;
    }
    if (code == 401 || code == 503 || code == 422) break;  // retrying won't help
    // "waiting" (the other bracelet hasn't reported yet) or a network blip.
    delay(TAP_RETRY_MS);
  }
  Serial.println("Pairing timed out (did the other bracelet report? is it linked?)");
  ledsError();
  if (peer[0]) detector.setCooldown(peer, millis(), RETRY_COOLDOWN_MS);
}

static void starLatest() {
  Serial.println("Star latest contact");
  JsonDocument req, resp;
  req["device"] = deviceId;
  addEvent(req);
  int code = api("POST", "/bracelets/star", &req, &resp);
  if (code == 200 && strcmp(resp["status"] | "", "starred") == 0) {
    Serial.printf("Starred %s\n", (const char*)(resp["peer_name"] | "?"));
    ledsStarred();
  } else if (code == 200) {
    Serial.println("Nobody to star yet");
    ledsNothingToStar();
  } else if (code == 409) {
    linkState = LINK_NO;
    ledsNotLinkedFlash();
  } else {
    ledsError();
  }
}

// ================= microphone (MIC_ENABLED) =================
#if MIC_ENABLED
static Recorder recorder;
static QueueHandle_t uploadQueue;
static char convoPeer[TRO_ID_LEN];  // bracelet we're recording with ("" = manual tap)

// Unix time in ms from NTP, or 0 if the clock isn't set yet. Lets the
// server line up the two bracelets' recordings of the same conversation.
static int64_t nowUnixMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  if (tv.tv_sec < 1600000000) return 0;
  return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

static void finishClip(const char* why) {
  Clip* c = recorder.stop();
  if (!c) return;
  Serial.printf("Recording stopped (%s): %s, %u s\n", why, c->conversation ? "conversation" : "voice note",
                (unsigned)((c->bytes - WAV_HEADER) / (MIC_RATE * 2)));
  if (c->bytes <= WAV_HEADER + MIC_RATE) {  // under half a second: nothing worth sending
    clipFree(c);
    return;
  }
  if (xQueueSend(uploadQueue, &c, 0) != pdTRUE) {
    Serial.println("Upload queue full, dropping clip");
    clipFree(c);
  }
}

static void startConversation(int connectionId, const char* peer) {
  if (recorder.active()) finishClip("new conversation");
  if (recorder.start(true, connectionId, MAX_CONVERSATION_S, nowUnixMs())) {
    strncpy(convoPeer, peer, sizeof(convoPeer) - 1);
    convoPeer[sizeof(convoPeer) - 1] = '\0';
    Serial.printf("Recording conversation %d (both people agreed)\n", connectionId);
  }
}

static void startVoiceNote() {
  if (recorder.active()) return;
  if (recorder.start(false, 0, MAX_VOICE_NOTE_S, nowUnixMs())) Serial.println("Recording a voice note: click to stop");
}

// Runs on its own task so a slow upload never blocks taps.
static void uploadTask(void*) {
  WiFiClientSecure tls;
  WiFiClient plain;
  tls.setInsecure();
  for (;;) {
    Clip* c = nullptr;
    if (xQueueReceive(uploadQueue, &c, portMAX_DELAY) != pdTRUE || !c) continue;
    String url = String(SERVER_URL) + "/bracelets/recordings?device=" + deviceId +
                 "&kind=" + (c->conversation ? "conversation" : "voice_note");
    if (c->conversation) url += "&connection_id=" + String(c->connectionId);
    if (c->startedAtMs) url += "&started_at=" + String((long long)c->startedAtMs);
    if (eventId > 0) url += "&event_id=" + String(eventId);
    for (int attempt = 0; attempt < 5; attempt++) {
      if (WiFi.status() != WL_CONNECTED) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        continue;
      }
      HTTPClient http;
      http.setConnectTimeout(UPLOAD_TIMEOUT_MS);
      http.setTimeout(UPLOAD_TIMEOUT_MS);
      bool ok = useTls() ? http.begin(tls, url) : http.begin(plain, url);
      if (!ok) break;
      http.addHeader("X-Bracelet-Key", BRACELET_KEY);
      http.addHeader("Content-Type", "audio/wav");
      int code = http.sendRequest("POST", c->buf, c->bytes);
      String body = code > 0 ? http.getString() : String();
      http.end();
      if (code == 201) {
        Serial.printf("Uploaded %u KB: %s\n", (unsigned)(c->bytes / 1024), body.c_str());
        break;
      }
      // 403: someone turned recording off, so the server refused it (and kept nothing).
      if (code == 403 || code == 409 || code == 413 || code == 422 || code == 401) {
        Serial.printf("Upload refused (%d): %s\n", code, body.c_str());
        break;
      }
      Serial.printf("Upload failed (%d), retrying\n", code);
      vTaskDelay(pdMS_TO_TICKS(5000 * (attempt + 1)));
    }
    clipFree(c);  // sent or given up: either way the audio leaves the bracelet
  }
}

static void micSetup() {
  uploadQueue = xQueueCreate(4, sizeof(Clip*));
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC; only used to line up two clips
  if (recorder.begin()) xTaskCreatePinnedToCore(uploadTask, "upload", 8192, nullptr, 1, nullptr, 0);
}

// Called every loop: end the recording when it's full or the two people walked apart.
static void micTick() {
  if (!recorder.active()) return;
  if (recorder.full()) {
    finishClip("max length");
    return;
  }
  if (recorder.isConversation() && convoPeer[0] && detector.msSinceHeard(convoPeer, millis()) > WALK_AWAY_MS) {
    finishClip("walked apart");
  }
}
#endif

// After anything slow, throw away beacons that piled up meanwhile and any
// half-finished holds, so old readings can't trigger a tap.
static void afterBusy() {
  xQueueReset(rxQueue);
  detector.clearProgress();
}

// ================= button =================
static bool btnRaw = false, btnDown = false, btnHoldFired = false;
static uint32_t btnRawAt = 0, btnDownAt = 0;
static uint32_t pendingClickAt = 0;  // a click waiting to see if it's a double-click

// One click, after the double-click window: stop a recording, or star.
static void onClick() {
#if MIC_ENABLED
  if (recorder.active()) {
    finishClip("button");
    return;
  }
#endif
  starLatest();
  afterBusy();
}

static void pumpButton() {
  uint32_t now = millis();
  bool raw = digitalRead(PIN_BUTTON) == LOW;
  if (raw != btnRaw) {
    btnRaw = raw;
    btnRawAt = now;
  }
  if (now - btnRawAt >= DEBOUNCE_MS && raw != btnDown) {
    btnDown = raw;
    if (btnDown) {
      btnDownAt = now;
      btnHoldFired = false;
    } else if (!btnHoldFired) {
#if MIC_ENABLED
      if (recorder.active()) {
        finishClip("button");  // stopping should feel instant: no double-click wait
      } else if (pendingClickAt && now - pendingClickAt <= DOUBLE_CLICK_MS) {
        pendingClickAt = 0;
        startVoiceNote();  // double-click
      } else {
        pendingClickAt = now ? now : 1;
      }
#else
      onClick();  // short click
#endif
    }
  }
  if (pendingClickAt && now - pendingClickAt > DOUBLE_CLICK_MS) {
    pendingClickAt = 0;
    onClick();
  }
  if (btnDown && !btnHoldFired && now - btnDownAt >= HOLD_PRESS_MS) {
    btnHoldFired = true;  // fires while still held, so it feels instant
    Serial.println("Manual tap (button hold)");
    tryPair("");
    afterBusy();
  }
}

// ================= setup / loop =================
static void makeDeviceId() {
  if (strlen(DEVICE_ID)) {
    strncpy(deviceId, DEVICE_ID, sizeof(deviceId) - 1);
    return;
  }
  uint8_t mac[6];
  esp_efuse_mac_get_default(mac);
  snprintf(deviceId, sizeof(deviceId), "TRO-%02X%02X%02X", mac[3], mac[4], mac[5]);
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // WiFi power save makes ESP-NOW miss most beacons
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("Connecting to %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    for (int i = 0; i < 6; i++) {
      ledsNoWifi();
      delay(50);
    }
    Serial.print(".");
  }
  Serial.printf("\nWiFi OK, IP=%s channel=%d\n", WiFi.localIP().toString().c_str(), WiFi.channel());
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  ledsAll(0);
  makeDeviceId();

  TapConfig cfg;
  cfg.touchRssi = RSSI_TOUCH;
  cfg.releaseRssi = RSSI_RELEASE;
  cfg.holdMs = TOUCH_HOLD_MS;
  cfg.cooldownMs = PAIR_COOLDOWN_MS;
  detector.setConfig(cfg);
  rxQueue = xQueueCreate(64, sizeof(Sample));

  Serial.printf("\ntrO bracelet %s\n", deviceId);
  Serial.printf("NFC sticker URL: %s/e/%d?b=%s\n", APP_URL, NFC_EVENT_ID, deviceId);

  connectWifi();
  if (useTls()) tlsClient.setInsecure();  // fine for a demo; see README to pin Render's CA
  espNowSetup();
  xTaskCreate(beaconTask, "beacon", 3072, nullptr, 2, nullptr);
#if MIC_ENABLED
  micSetup();
#endif

  wakeServer();
  checkStatus();
  afterBusy();
  Serial.printf("Ready. Touch threshold %d dBm, hold %d ms\n", RSSI_TOUCH, TOUCH_HOLD_MS);
}

void loop() {
  uint32_t now = millis();

  // Beacons heard since last time -> maybe a tap.
  Sample s;
  char peer[TRO_ID_LEN];
  while (xQueueReceive(rxQueue, &s, 0) == pdTRUE) {
    if (detector.onBeacon(s.id, s.rssi, s.at, peer)) {
#if MIC_ENABLED
      if (recorder.isConversation()) finishClip("tapped someone else");
#endif
      tryPair(peer);
      afterBusy();
      break;
    }
  }
  detector.tick(now);

  pumpButton();
#if MIC_ENABLED
  micTick();
#endif

  if ((int32_t)(millis() - nextStatusAt) >= 0) checkStatus();

  if (WiFi.status() != WL_CONNECTED) ledsNoWifi();
#if MIC_ENABLED
  else if (recorder.active()) recorder.isConversation() ? ledsRecording() : ledsVoiceNote();
#endif
  else if (!serverReachable) ledsNoServer();
  else if (linkState == LINK_NO) ledsUnlinked();
  else ledsBreathe();

  // Calibration printout: hold two bracelets together, then 30 cm apart.
  static uint32_t lastDbg = 0;
  if (millis() - lastDbg > 1000) {
    lastDbg = millis();
    const TapDetector::Peer* p = detector.nearest(millis());
    if (p)
      Serial.printf("near %s rssi %d (raw %d), %d bracelet(s) in range\n", p->id, p->smoothed, p->last,
                    detector.count(millis()));
  }
  delay(5);
}

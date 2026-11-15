// =====================================================================
// trO bracelet firmware: Seeed XIAO ESP32-S3, no-mic build
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
// =====================================================================

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_mac.h>
#include <esp_now.h>
#include <esp_wifi.h>

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

// After anything slow, throw away beacons that piled up meanwhile and any
// half-finished holds, so old readings can't trigger a tap.
static void afterBusy() {
  xQueueReset(rxQueue);
  detector.clearProgress();
}

// ================= button =================
static bool btnRaw = false, btnDown = false, btnHoldFired = false;
static uint32_t btnRawAt = 0, btnDownAt = 0;

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
      starLatest();  // short click
      afterBusy();
    }
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
      tryPair(peer);
      afterBusy();
      break;
    }
  }
  detector.tick(now);

  pumpButton();

  if ((int32_t)(millis() - nextStatusAt) >= 0) checkStatus();

  if (WiFi.status() != WL_CONNECTED) ledsNoWifi();
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

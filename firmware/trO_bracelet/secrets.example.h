// Copy this file to secrets.h (same folder) and fill it in.
// secrets.h is in .gitignore: never commit WiFi passwords or the bracelet key.
#pragma once

// Both bracelets must join the SAME network: ESP-NOW only works between
// devices on the same WiFi channel. A phone hotspot is easiest (USC's
// eduroam / USC Secure Wireless need enterprise logins the ESP32 can't do).
// iPhone: turn on "Maximize Compatibility" so the hotspot uses 2.4 GHz.
#define WIFI_SSID "your-hotspot-name"
#define WIFI_PASS "your-hotspot-password"

// The trO backend. Either the live one on Render:
#define SERVER_URL "https://tro-api.onrender.com"
// ...or a laptop on the same hotspot running ./scripts/local-server.sh:
// #define SERVER_URL "http://172.20.10.8:8000"

// BRACELET_API_KEY: on Render it's under tro-api > Environment; locally it's
// in backend/.env (local-server.sh creates it).
#define BRACELET_KEY "paste-the-bracelet-key-here"

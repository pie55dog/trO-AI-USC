// TapDetector: decides when another bracelet is being "held against" this one.
//
// Plain C++ (no Arduino headers) so it can be unit-tested on a laptop:
//   firmware/test/run_host_tests.sh
//
// Feed it every beacon you hear (peer id, RSSI, time). It keeps one small
// record per nearby bracelet, smooths the RSSI, and fires once when a peer
// has stayed above the "touching" level for holdMs. Compared with tracking
// only the most recent beacon, this keeps working with many bracelets in
// the room: a third bracelet across the room can't reset someone's tap.
#pragma once

#include <stdint.h>
#include <string.h>

#ifndef TRO_ID_LEN
#define TRO_ID_LEN 16  // bytes, including the NUL
#endif

struct TapConfig {
  int touchRssi = -40;        // smoothed RSSI at or above this = touching
  int releaseRssi = -47;      // drops below this = no longer touching (hysteresis)
  uint32_t holdMs = 500;      // must stay touching this long
  uint8_t minSamples = 3;     // ...and be heard at least this many times meanwhile
  uint32_t staleMs = 600;     // not heard for this long = gone
  uint32_t cooldownMs = 10000;  // after a tap, ignore that peer this long
};

class TapDetector {
 public:
  static const int MAX_PEERS = 16;

  struct Peer {
    char id[TRO_ID_LEN];
    bool used;
    bool heard;             // at least one beacon so far
    int smoothed;           // RSSI, smoothed (dBm)
    int last;               // last raw RSSI
    uint32_t lastSeen;
    uint32_t touchingSince; // 0 = not touching
    uint8_t samples;        // beacons heard since touchingSince
    uint32_t cooldownUntil; // 0 = none
  };

  explicit TapDetector(const TapConfig& cfg = TapConfig()) : cfg_(cfg) { clear(); }

  const TapConfig& config() const { return cfg_; }
  void setConfig(const TapConfig& cfg) { cfg_ = cfg; }

  void clear() { memset(peers_, 0, sizeof(peers_)); }

  // Forget any half-finished holds (after the loop was busy for a while),
  // keeping cooldowns so a just-paired peer doesn't fire again.
  void clearProgress() {
    for (auto& p : peers_) {
      p.touchingSince = 0;
      p.samples = 0;
    }
  }

  // One beacon heard. Returns true if this beacon completes a tap; the
  // peer's id is copied to outPeer (TRO_ID_LEN bytes). `now` is millis().
  bool onBeacon(const char* id, int rssi, uint32_t now, char* outPeer) {
    if (!id || !id[0]) return false;
    Peer* p = find(id);
    if (!p) p = add(id, now);
    if (!p->heard || now - p->lastSeen > cfg_.staleMs) {
      // Fresh start (new or reappeared): no history to smooth against.
      p->smoothed = rssi;
      p->touchingSince = 0;
      p->samples = 0;
    } else {
      // Exponential average, weight 1/2 on the new sample: steady enough to
      // ignore one bad reading, quick enough for a half-second hold.
      p->smoothed = (p->smoothed + rssi) / 2;
    }
    p->last = rssi;
    p->lastSeen = now;
    p->heard = true;

    if (inCooldown(*p, now)) {
      p->touchingSince = 0;
      p->samples = 0;
      return false;
    }

    if (p->touchingSince == 0) {
      if (p->smoothed >= cfg_.touchRssi) {
        p->touchingSince = now ? now : 1;
        p->samples = 1;
      }
      return false;
    }

    if (p->smoothed < cfg_.releaseRssi) {
      p->touchingSince = 0;
      p->samples = 0;
      return false;
    }
    if (p->samples < 255) p->samples++;
    if (now - p->touchingSince >= cfg_.holdMs && p->samples >= cfg_.minSamples) {
      p->touchingSince = 0;
      p->samples = 0;
      p->cooldownUntil = now + cfg_.cooldownMs;
      if (p->cooldownUntil == 0) p->cooldownUntil = 1;
      if (outPeer) {
        strncpy(outPeer, p->id, TRO_ID_LEN - 1);
        outPeer[TRO_ID_LEN - 1] = '\0';
      }
      return true;
    }
    return false;
  }

  // Call regularly: drops holds for peers that went quiet.
  void tick(uint32_t now) {
    for (auto& p : peers_) {
      if (p.used && p.touchingSince && now - p.lastSeen > cfg_.staleMs) {
        p.touchingSince = 0;
        p.samples = 0;
      }
    }
  }

  // Set (or shorten/extend) the cooldown for one peer, e.g. a short one
  // after a failed pairing so the two people can simply try again.
  void setCooldown(const char* id, uint32_t now, uint32_t ms) {
    Peer* p = find(id);
    if (!p) return;
    p->cooldownUntil = now + ms;
    if (p->cooldownUntil == 0) p->cooldownUntil = 1;
  }

  // The loudest peer heard within staleMs, for the calibration printout.
  const Peer* nearest(uint32_t now) const {
    const Peer* best = nullptr;
    for (auto& p : peers_) {
      if (!p.used || now - p.lastSeen > cfg_.staleMs) continue;
      if (!best || p.smoothed > best->smoothed) best = &p;
    }
    return best;
  }

  // Smoothed RSSI of one peer, or -127 if unknown.
  int rssiOf(const char* id) const {
    for (auto& p : peers_)
      if (p.used && strncmp(p.id, id, TRO_ID_LEN) == 0) return p.smoothed;
    return -127;
  }

  int count(uint32_t now) const {
    int n = 0;
    for (auto& p : peers_)
      if (p.used && now - p.lastSeen <= cfg_.staleMs) n++;
    return n;
  }

  const Peer* peers() const { return peers_; }

 private:
  bool inCooldown(const Peer& p, uint32_t now) const {
    // Signed difference so it still works when millis() wraps (~49 days).
    return p.cooldownUntil && (int32_t)(p.cooldownUntil - now) > 0;
  }

  Peer* find(const char* id) {
    for (auto& p : peers_)
      if (p.used && strncmp(p.id, id, TRO_ID_LEN) == 0) return &p;
    return nullptr;
  }

  // New record, replacing the one heard longest ago if the table is full.
  Peer* add(const char* id, uint32_t now) {
    Peer* slot = nullptr;
    for (auto& p : peers_)
      if (!p.used) { slot = &p; break; }
    if (!slot) {
      slot = &peers_[0];
      for (auto& p : peers_)
        if (now - p.lastSeen > now - slot->lastSeen) slot = &p;
    }
    memset(slot, 0, sizeof(*slot));
    slot->used = true;
    strncpy(slot->id, id, TRO_ID_LEN - 1);
    return slot;
  }

  TapConfig cfg_;
  Peer peers_[MAX_PEERS];
};

// Host tests for TapDetector (no hardware needed): ./run_host_tests.sh
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "../trO_bracelet/TapDetector.h"

static int failures = 0;
#define CHECK(cond)                                                        \
  do {                                                                     \
    if (!(cond)) {                                                         \
      std::printf("  FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond);        \
      failures++;                                                          \
    }                                                                      \
  } while (0)

// Feed one peer a constant RSSI every `every` ms from t0 to t1. Returns the
// time the tap fired, or 0.
static uint32_t feed(TapDetector& d, const char* id, int rssi, uint32_t t0, uint32_t t1, uint32_t every = 100) {
  char out[TRO_ID_LEN];
  for (uint32_t t = t0; t <= t1; t += every)
    if (d.onBeacon(id, rssi, t, out)) {
      if (std::strcmp(out, id) != 0) { std::printf("  FAIL wrong peer %s\n", out); failures++; }
      return t;
    }
  return 0;
}

static void test_hold_fires_once() {
  TapDetector d;
  uint32_t fired = feed(d, "TRO-2", -30, 1000, 3000);
  CHECK(fired >= 1500 && fired <= 1700);  // ~holdMs after first strong beacon
  // Still touching: cooldown stops a second tap.
  CHECK(feed(d, "TRO-2", -30, fired + 100, fired + 5000) == 0);
}

static void test_far_never_fires() {
  TapDetector d;
  CHECK(feed(d, "TRO-2", -60, 0, 10000) == 0);
}

static void test_brief_touch_doesnt_fire() {
  TapDetector d;
  CHECK(feed(d, "TRO-2", -30, 1000, 1300) == 0);
  CHECK(feed(d, "TRO-2", -70, 1400, 3000) == 0);
}

static void test_one_noisy_sample_is_tolerated() {
  TapDetector d;
  char out[TRO_ID_LEN];
  uint32_t fired = 0;
  for (uint32_t t = 1000; t <= 3000 && !fired; t += 100) {
    int rssi = (t == 1200) ? -52 : -30;  // one bad reading mid-hold
    if (d.onBeacon("TRO-2", rssi, t, out)) fired = t;
  }
  CHECK(fired != 0 && fired <= 1700);
}

static void test_other_bracelets_dont_reset_hold() {
  // The original sketch tracked only the latest beacon, so a far bracelet
  // interleaved with the near one could block the tap. Not any more.
  TapDetector d;
  char out[TRO_ID_LEN];
  uint32_t fired = 0;
  for (uint32_t t = 1000; t <= 3000 && !fired; t += 50) {
    if (t % 100 == 0) {
      if (d.onBeacon("TRO-2", -32, t, out)) fired = t;
    } else {
      d.onBeacon("TRO-7", -75, t, out);
      d.onBeacon("TRO-9", -68, t, out);
    }
  }
  CHECK(fired != 0);
  CHECK(std::strcmp(out, "TRO-2") == 0);
  CHECK(d.count(fired) == 3);
}

static void test_gap_resets_hold() {
  TapDetector d;
  CHECK(feed(d, "TRO-2", -30, 1000, 1300) == 0);
  // Silent for longer than staleMs, then back: must hold the full time again.
  uint32_t fired = feed(d, "TRO-2", -30, 2500, 4000);
  CHECK(fired >= 3000);
  d.tick(fired);
}

static void test_short_cooldown_allows_retry() {
  TapDetector d;
  uint32_t fired = feed(d, "TRO-2", -30, 1000, 3000);
  CHECK(fired);
  d.setCooldown("TRO-2", fired, 1000);
  uint32_t again = feed(d, "TRO-2", -30, fired + 100, fired + 4000);
  CHECK(again >= fired + 1000 && again <= fired + 1800);
}

static void test_wraparound() {
  TapDetector d;
  uint32_t start = 0xFFFFFF00u;  // millis() about to wrap
  char out[TRO_ID_LEN];
  uint32_t fired = 0;
  for (uint32_t i = 0; i < 30 && !fired; i++)
    if (d.onBeacon("TRO-2", -30, start + i * 100, out)) fired = start + i * 100;
  CHECK(fired != 0);
  // Cooldown spans the wrap and still holds.
  bool again = false;
  for (uint32_t i = 1; i < 50; i++) again |= d.onBeacon("TRO-2", -30, fired + i * 100, out);
  CHECK(!again);
}

static void test_table_full_evicts_oldest() {
  TapDetector d;
  char id[TRO_ID_LEN];
  for (int i = 0; i < TapDetector::MAX_PEERS + 4; i++) {
    std::snprintf(id, sizeof id, "P%02d", i);
    d.onBeacon(id, -80, 1000 + i, nullptr);
  }
  CHECK(feed(d, "TRO-2", -30, 2000, 4000) != 0);
}

int main() {
  test_hold_fires_once();
  test_far_never_fires();
  test_brief_touch_doesnt_fire();
  test_one_noisy_sample_is_tolerated();
  test_other_bracelets_dont_reset_hold();
  test_gap_resets_hold();
  test_short_cooldown_allows_retry();
  test_wraparound();
  test_table_full_evicts_oldest();
  if (failures) { std::printf("%d check(s) failed\n", failures); return 1; }
  std::printf("TapDetector: all tests passed\n");
  return 0;
}

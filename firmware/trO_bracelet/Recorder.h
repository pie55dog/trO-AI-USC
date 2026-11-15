// trO bracelet microphone: records conversations and voice notes into PSRAM
// as 16 kHz, 16-bit mono WAV, ready to POST to /bracelets/recordings.
//
// Only compiled when MIC_ENABLED is 1 (config.h). Two kinds of mic work:
//   * MIC_TYPE_PDM: the XIAO ESP32-S3 *Sense* camera board's built-in mic
//     (clock GPIO42, data GPIO41). Nothing to wire.
//   * MIC_TYPE_I2S: an I2S MEMS mic such as the INMP441 (pins in config.h).
//
// The mic runs all the time on its own task, so starting a recording is
// instant and the I2S buffer never overflows. Samples are only kept while a
// recording is active. Needs PSRAM: Arduino IDE > Tools > PSRAM > "OPI PSRAM".
#pragma once

#include "config.h"

#if MIC_ENABLED

#include <ESP_I2S.h>
#include <esp_heap_caps.h>

static const uint32_t MIC_RATE = 16000;
static const size_t WAV_HEADER = 44;

// One finished (or in-progress) clip. The buffer starts with a WAV header.
struct Clip {
  uint8_t* buf = nullptr;
  size_t bytes = 0;     // header + samples so far
  size_t capacity = 0;  // whole buffer
  bool conversation = false;
  int connectionId = 0;
  int64_t startedAtMs = 0;  // Unix ms from NTP; 0 if the clock isn't set
};

static void clipFree(Clip* c) {
  if (!c) return;
  if (c->buf) heap_caps_free(c->buf);
  delete c;
}

static void writeLE32(uint8_t* p, uint32_t v) {
  p[0] = v;
  p[1] = v >> 8;
  p[2] = v >> 16;
  p[3] = v >> 24;
}
static void writeLE16(uint8_t* p, uint16_t v) {
  p[0] = v;
  p[1] = v >> 8;
}

// Standard 44-byte PCM WAV header for `dataBytes` of 16-bit mono audio.
static void writeWavHeader(uint8_t* h, uint32_t dataBytes) {
  memcpy(h, "RIFF", 4);
  writeLE32(h + 4, 36 + dataBytes);
  memcpy(h + 8, "WAVEfmt ", 8);
  writeLE32(h + 16, 16);           // fmt chunk size
  writeLE16(h + 20, 1);            // PCM
  writeLE16(h + 22, 1);            // mono
  writeLE32(h + 24, MIC_RATE);     // sample rate
  writeLE32(h + 28, MIC_RATE * 2); // byte rate
  writeLE16(h + 32, 2);            // block align
  writeLE16(h + 34, 16);           // bits per sample
  memcpy(h + 36, "data", 4);
  writeLE32(h + 40, dataBytes);
}

class Recorder {
 public:
  bool begin() {
    if (!psramFound()) {
      Serial.println("Mic: no PSRAM. Arduino IDE > Tools > PSRAM > OPI PSRAM, then re-flash");
      return false;
    }
    lock_ = xSemaphoreCreateMutex();
#if MIC_TYPE == MIC_TYPE_PDM
    i2s_.setPinsPdmRx(PIN_MIC_CLK, PIN_MIC_DATA);
    bool ok = i2s_.begin(I2S_MODE_PDM_RX, MIC_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
#else
    i2s_.setPins(PIN_MIC_BCLK, PIN_MIC_WS, -1, PIN_MIC_SD);
    bool ok = i2s_.begin(I2S_MODE_STD, MIC_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT);
#endif
    if (!ok) {
      Serial.println("Mic: I2S start failed (check MIC_TYPE and pins in config.h)");
      return false;
    }
    xTaskCreatePinnedToCore(task, "mic", 4096, this, 3, nullptr, 1);
    ready_ = true;
    Serial.println("Mic ready");
    return true;
  }

  bool ready() const { return ready_; }
  bool active() const { return clip_ != nullptr; }
  bool isConversation() const { return clip_ && clip_->conversation; }
  bool full() const { return full_; }
  uint32_t seconds() const { return clip_ ? (clip_->bytes - WAV_HEADER) / (MIC_RATE * 2) : 0; }

  // Start a new clip. Fails if one is already running or there's no memory
  // (e.g. two earlier clips still waiting to upload).
  bool start(bool conversation, int connectionId, uint32_t maxSeconds, int64_t startedAtMs) {
    if (!ready_ || clip_) return false;
    Clip* c = new Clip();
    c->capacity = WAV_HEADER + (size_t)maxSeconds * MIC_RATE * 2;
    c->buf = (uint8_t*)heap_caps_malloc(c->capacity, MALLOC_CAP_SPIRAM);
    if (!c->buf) {
      Serial.println("Mic: not enough PSRAM for another clip (uploads still pending?)");
      delete c;
      return false;
    }
    c->bytes = WAV_HEADER;
    c->conversation = conversation;
    c->connectionId = connectionId;
    c->startedAtMs = startedAtMs;
    xSemaphoreTake(lock_, portMAX_DELAY);
    full_ = false;
    clip_ = c;
    xSemaphoreGive(lock_);
    return true;
  }

  // Stop and hand back the clip with its header filled in (caller frees it).
  Clip* stop() {
    xSemaphoreTake(lock_, portMAX_DELAY);
    Clip* c = clip_;
    clip_ = nullptr;
    full_ = false;
    xSemaphoreGive(lock_);
    if (c) writeWavHeader(c->buf, c->bytes - WAV_HEADER);
    return c;
  }

 private:
  static void task(void* arg) {
    Recorder* self = (Recorder*)arg;
#if MIC_TYPE == MIC_TYPE_PDM
    static int16_t raw[512];
#else
    static int32_t raw[512];
#endif
    static int16_t pcm[512];
    for (;;) {
      size_t got = self->i2s_.readBytes((char*)raw, sizeof(raw));
      size_t n = got / sizeof(raw[0]);
      for (size_t i = 0; i < n; i++) {
#if MIC_TYPE == MIC_TYPE_PDM
        int32_t v = (int32_t)raw[i] << MIC_GAIN_SHIFT;
#else
        int32_t v = (raw[i] >> 14) << MIC_GAIN_SHIFT;  // INMP441: 24-bit audio in a 32-bit slot
#endif
        pcm[i] = v > 32767 ? 32767 : v < -32768 ? -32768 : (int16_t)v;
      }
      xSemaphoreTake(self->lock_, portMAX_DELAY);
      Clip* c = self->clip_;
      if (c && !self->full_) {
        size_t room = c->capacity - c->bytes;
        size_t bytes = n * 2;
        if (bytes >= room) {
          bytes = room;
          self->full_ = true;  // the main loop notices and stops the clip
        }
        memcpy(c->buf + c->bytes, pcm, bytes);
        c->bytes += bytes;
      }
      xSemaphoreGive(self->lock_);
    }
  }

  I2SClass i2s_;
  SemaphoreHandle_t lock_ = nullptr;
  Clip* volatile clip_ = nullptr;
  volatile bool full_ = false;
  bool ready_ = false;
};

#endif  // MIC_ENABLED

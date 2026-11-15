/** Phone mic: resampling, WAV encoding, and when clips start, stop and upload. */

import { describe, expect, it, vi } from "vitest";
import { ApiError, type Connection } from "../api";
import { Downsampler, encodeWav, SAMPLE_RATE, SampleStore, type AudioSource } from "../phoneMic/audio";
import { MAX_CONVERSATION_S, PhoneMicController, PREROLL_S, type UploadParams } from "../phoneMic/controller";

describe("audio helpers", () => {
  it("downsamples 48 kHz to 16 kHz across chunk boundaries", () => {
    const d = new Downsampler(48000);
    const a = d.process(new Float32Array(1000).fill(0.5));
    const b = d.process(new Float32Array(2000).fill(0.5));
    expect(a.length + b.length).toBe(1000);
    expect(a[0]).toBe(Math.round(0.5 * 32767));
  });

  it("encodes a WAV header the backend can read", async () => {
    const wav = encodeWav(new Int16Array([1, -1, 300]));
    const v = new DataView(await wav.arrayBuffer());
    const tag = (o: number) => String.fromCharCode(...[0, 1, 2, 3].map((i) => v.getUint8(o + i)));
    expect([tag(0), tag(8), tag(12), tag(36)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect(v.getUint32(24, true)).toBe(SAMPLE_RATE);
    expect(v.getUint32(40, true)).toBe(6);
    expect(v.getInt16(44 + 4, true)).toBe(300);
  });

  it("slices across chunks, trims, and keeps wall-clock times through gaps", () => {
    const s = new SampleStore();
    s.append(new Int16Array([1, 2, 3, 4]), 1000);
    s.append(new Int16Array([5, 6, 7, 8]), 900_000); // the phone paused in between
    expect([...s.slice(2, 6)]).toEqual([3, 4, 5, 6]);
    expect(s.wallMsAt(4)).toBe(900_000);
    s.trimBefore(5);
    expect(s.first).toBe(4);
    expect([...s.slice(0, 8)]).toEqual([5, 6, 7, 8]);
  });
});

/** A mic that "hears" whatever seconds of audio the test adds. */
class FakeSource implements AudioSource {
  store = new SampleStore();
  level = 0.3;
  started = false;
  async start() {
    this.started = true;
  }
  stop() {
    this.started = false;
  }
  hear(seconds: number) {
    this.store.append(new Int16Array(Math.round(seconds * SAMPLE_RATE)).fill(100), 1_763_190_000_000 + (this.store.end / SAMPLE_RATE) * 1000);
  }
}

const person = (id: number, name: string, consent = true, at = id): Connection => ({
  user_id: id + 100, connection_id: id, name, position: null, school: null, major: null, bio: null, photo_url: null,
  recorded: false, both_consented: consent, contact: {}, tapped_at: new Date(1_763_190_000_000 + at * 1000).toISOString(),
});

function setup(initial: Connection[] = [], upload?: (params: UploadParams) => Promise<unknown>) {
  const source = new FakeSource();
  const uploads: { params: UploadParams; seconds: number }[] = [];
  const c = new PhoneMicController({
    source,
    eventId: 3,
    connections: async () => initial,
    upload: async (_e, wav, params) => {
      uploads.push({ params, seconds: (wav.size - 44) / 2 / SAMPLE_RATE });
      return upload ? upload(params) : { id: 1 };
    },
    setInterval: () => 0,
    clearInterval: () => undefined,
    sleep: async () => undefined,
  });
  return { c, source, uploads };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("PhoneMicController", () => {
  it("ignores taps from before the mic was on, then records the next one with pre-roll", async () => {
    const old = person(1, "Ada Old");
    const { c, source, uploads } = setup([old]);
    await c.start();
    expect(source.started).toBe(true);
    source.hear(20);
    c.handleConnections([old]);
    expect(c.state.active).toBeNull();

    c.handleConnections([person(2, "Bob Li"), old]);
    expect(c.state.active).toMatchObject({ kind: "conversation", name: "Bob Li" });
    source.hear(30);
    c.endConversation();
    await flush();
    expect(uploads).toHaveLength(1);
    expect(uploads[0].params).toMatchObject({ kind: "conversation", connectionId: 2 });
    expect(uploads[0].seconds).toBeCloseTo(30 + PREROLL_S);
    expect(uploads[0].params.startedAt).toBe(1_763_190_000_000 + (20 - PREROLL_S) * 1000);
    expect(c.state.clips[0]).toMatchObject({ label: "Conversation with Bob", status: "sent" });
  });

  it("a new tap ends the last conversation where the new one starts", async () => {
    const { c, source, uploads } = setup();
    await c.start();
    source.hear(10);
    c.handleConnections([person(1, "Bob Li")]);
    source.hear(40);
    c.handleConnections([person(2, "Cara Wu"), person(1, "Bob Li")]);
    expect(c.state.active).toMatchObject({ name: "Cara Wu" });
    await flush();
    expect(uploads[0].params.connectionId).toBe(1);
    expect(uploads[0].seconds).toBeCloseTo(40); // 6 s pre-roll in, 6 s handed to Cara
  });

  it("doesn't record when either person said no", async () => {
    const { c, source, uploads } = setup();
    await c.start();
    source.hear(10);
    c.handleConnections([person(1, "Bob Li", false)]);
    expect(c.state.active).toBeNull();
    expect(c.state.notice).toMatch(/Not recording/);
    source.hear(30);
    c.tick();
    await flush();
    expect(uploads).toHaveLength(0);
  });

  it("stops at the 3-minute limit and keeps memory bounded", async () => {
    const { c, source, uploads } = setup();
    await c.start();
    source.hear(5);
    c.handleConnections([person(1, "Bob Li")]);
    for (let i = 0; i < 200; i++) {
      source.hear(1);
      c.tick();
    }
    await flush();
    expect(uploads).toHaveLength(1);
    expect(uploads[0].seconds).toBeCloseTo(MAX_CONVERSATION_S);
    // Idle again: only the pre-roll window is kept.
    expect((source.store.end - source.store.first) / SAMPLE_RATE).toBeLessThanOrEqual(PREROLL_S + 2);
  });

  it("records voice notes and reports refused or failed uploads", async () => {
    const results = [new ApiError(403, "no"), new ApiError(0, "offline")];
    const { c, source, uploads } = setup([], async () => {
      throw results.shift() ?? new ApiError(0, "offline");
    });
    await c.start();
    c.toggleVoiceNote();
    source.hear(5);
    c.toggleVoiceNote();
    await flush();
    expect(uploads[0].params).toMatchObject({ kind: "voice_note" });
    expect(c.state.clips[0].status).toBe("refused");

    c.toggleVoiceNote();
    source.hear(3);
    c.toggleVoiceNote();
    await vi.waitFor(() => expect(c.state.clips[0].status).toBe("failed"));
    expect(uploads.length).toBe(1 + 4); // retried
  });

  it("drops clips too short to be useful", async () => {
    const { c, source, uploads } = setup();
    await c.start();
    c.toggleVoiceNote();
    source.hear(0.3);
    c.toggleVoiceNote();
    await flush();
    expect(uploads).toHaveLength(0);
  });

  it("turning off saves the conversation in progress", async () => {
    const { c, source, uploads } = setup();
    await c.start();
    c.handleConnections([person(1, "Bob Li")]);
    source.hear(12);
    c.stop();
    await flush();
    expect(uploads).toHaveLength(1);
    expect(source.started).toBe(false);
    expect(c.state.on).toBe(false);
  });
});

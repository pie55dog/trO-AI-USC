/**
 * Phone mic audio: capture the microphone as 16 kHz 16-bit mono (the same
 * format the bracelet mic sends) into a rolling in-memory buffer, then cut
 * any stretch of it out as a WAV file.
 *
 * Why raw samples instead of MediaRecorder: the server measures loudness on
 * WAV clips to tell who said what (backend/app/speakers.py), and slicing a
 * running MediaRecorder stream into separate valid files isn't possible.
 *
 * Memory: 16 kHz x 2 bytes = 32 KB a second, so a 3-minute conversation plus
 * the pre-roll is about 6 MB. Everything older than what's still needed is
 * dropped (see SampleStore.trimBefore).
 */

export const SAMPLE_RATE = 16000;

/**
 * Box-filter downsampler (e.g. 48 kHz -> 16 kHz). Each output sample is the
 * average of the input samples it covers, which is a cheap low-pass that's
 * plenty for speech. Keeps its place between chunks.
 */
export class Downsampler {
  private readonly step: number;
  private sum = 0;
  private count = 0;
  private index = 0;
  private boundary: number;

  constructor(inRate: number, outRate = SAMPLE_RATE) {
    this.step = inRate / outRate;
    this.boundary = this.step;
  }

  process(input: Float32Array): Int16Array {
    const out = new Int16Array(Math.ceil(input.length / this.step) + 1);
    let n = 0;
    for (let i = 0; i < input.length; i++) {
      this.sum += input[i];
      this.count++;
      this.index++;
      if (this.index >= this.boundary) {
        const v = Math.max(-1, Math.min(1, this.sum / this.count));
        out[n++] = Math.round(v * 32767);
        this.sum = 0;
        this.count = 0;
        this.boundary += this.step;
      }
    }
    return out.subarray(0, n);
  }
}

interface Chunk {
  /** Absolute sample index of the chunk's first sample. */
  start: number;
  samples: Int16Array;
  /** Phone clock (Unix ms) when the first sample was heard. */
  wallMs: number;
}

/**
 * Captured samples, addressed by absolute sample index (0 = first sample
 * since the mic started). Each chunk remembers its wall-clock time, so a gap
 * (the phone paused audio while the screen was off) doesn't shift the times.
 */
export class SampleStore {
  private chunks: Chunk[] = [];
  /** Total samples ever appended; also the index of the next sample. */
  end = 0;

  append(samples: Int16Array, wallMs: number): void {
    if (!samples.length) return;
    this.chunks.push({ start: this.end, samples, wallMs });
    this.end += samples.length;
  }

  /** Oldest sample index still held. */
  get first(): number {
    return this.chunks.length ? this.chunks[0].start : this.end;
  }

  /** Drop whole chunks that end before `index`. */
  trimBefore(index: number): void {
    while (this.chunks.length && this.chunks[0].start + this.chunks[0].samples.length <= index) this.chunks.shift();
  }

  /** Samples [from, to), clamped to what's held. */
  slice(from: number, to: number): Int16Array {
    from = Math.max(from, this.first);
    to = Math.min(to, this.end);
    const out = new Int16Array(Math.max(0, to - from));
    for (const c of this.chunks) {
      const a = Math.max(from, c.start);
      const b = Math.min(to, c.start + c.samples.length);
      if (a < b) out.set(c.samples.subarray(a - c.start, b - c.start), a - from);
    }
    return out;
  }

  /** Phone clock (Unix ms) of the sample at `index`, or null if it's gone. */
  wallMsAt(index: number): number | null {
    index = Math.max(index, this.first);
    for (const c of this.chunks) {
      if (index < c.start + c.samples.length) return c.wallMs + ((index - c.start) / SAMPLE_RATE) * 1000;
    }
    return null;
  }
}

/** 16-bit mono PCM -> a WAV file the backend's decode_wav reads. */
export function encodeWav(samples: Int16Array, rate = SAMPLE_RATE): Blob {
  const header = new ArrayBuffer(44);
  const v = new DataView(header);
  const text = (offset: number, s: string) => [...s].forEach((ch, i) => v.setUint8(offset + i, ch.charCodeAt(0)));
  const bytes = samples.length * 2;
  text(0, "RIFF");
  v.setUint32(4, 36 + bytes, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true); // fmt chunk size
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); // byte rate
  v.setUint16(32, 2, true); // block align
  v.setUint16(34, 16, true); // bits per sample
  text(36, "data");
  v.setUint32(40, bytes, true);
  // WAV is little-endian; so is every phone, but don't count on it.
  const body = new DataView(new ArrayBuffer(bytes));
  samples.forEach((s, i) => body.setInt16(i * 2, s, true));
  return new Blob([header, body.buffer], { type: "audio/wav" });
}

/** What the controller needs from the mic (a fake one in tests). */
export interface AudioSource {
  readonly store: SampleStore;
  /** 0..1, the loudness of the last chunk, for the level meter. */
  readonly level: number;
  start(): Promise<void>;
  stop(): void;
}

/**
 * The real microphone through Web Audio. `start()` must be called from a tap
 * or click: iPhones only allow audio to start from a user gesture.
 */
export class MicCapture implements AudioSource {
  readonly store = new SampleStore();
  level = 0;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private onVisible = () => {
    if (document.visibilityState === "visible" && this.ctx?.state !== "running") void this.ctx?.resume();
  };

  async start(): Promise<void> {
    if (this.ctx) return;
    // Create and resume the context before the first await, while we're still
    // inside the tap that started this (iOS rule).
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctor();
    this.ctx = ctx;
    void ctx.resume();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          // Automatic gain would flatten the loud-me / quiet-them difference
          // the server uses to tell speakers apart. Echo cancellation isn't
          // needed: nothing is playing.
          autoGainControl: false,
          echoCancellation: false,
          noiseSuppression: true,
        },
      });
    } catch (err) {
      this.stop();
      throw err;
    }
    const source = ctx.createMediaStreamSource(this.stream);
    // ScriptProcessorNode is deprecated but is the one capture path every
    // phone browser supports without a separate worklet file.
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const down = new Downsampler(ctx.sampleRate);
    proc.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      const samples = down.process(input);
      let sq = 0;
      for (let i = 0; i < input.length; i++) sq += input[i] * input[i];
      this.level = Math.min(1, Math.sqrt(sq / input.length) * 4);
      this.store.append(samples, Date.now() - (samples.length / SAMPLE_RATE) * 1000);
    };
    // Some browsers only run the processor when it's connected to the output;
    // a muted gain keeps it running without playing the mic back.
    const mute = ctx.createGain();
    mute.gain.value = 0;
    source.connect(proc);
    proc.connect(mute);
    mute.connect(ctx.destination);
    document.addEventListener("visibilitychange", this.onVisible);
  }

  stop(): void {
    document.removeEventListener("visibilitychange", this.onVisible);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.level = 0;
  }
}

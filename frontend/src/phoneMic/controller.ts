/**
 * The phone mic's brain: the bracelets do the taps, the phone does the
 * listening. Mirrors the bracelet mic build (firmware/README.md, "Adding the mic"):
 *
 *   new tap, both said yes   start a conversation clip (with a few seconds of pre-roll,
 *                            since the phone only hears about the tap on its next check)
 *   new tap, someone said no nothing recorded, contact swap only
 *   next tap / End / 3 min   the clip stops and uploads
 *   voice note button        a voice note clip (30 s max)
 *
 * Taps are found by polling GET /events/{id}/connections, the same list the
 * dashboard shows. Clips go to POST /events/{id}/recordings, which checks
 * consent again and runs the same transcription and notes as bracelet clips.
 */

import { ApiError, type Connection } from "../api";
import { encodeWav, SAMPLE_RATE, type AudioSource } from "./audio";

export const PREROLL_S = 6;
export const MAX_CONVERSATION_S = 180;
export const MAX_VOICE_NOTE_S = 30;
export const MIN_CLIP_S = 1;
export const POLL_MS = 2500;
const TICK_MS = 250;
/** Waits before each upload try; network errors and a sleeping server are retried. */
const RETRY_DELAYS_MS = [0, 3000, 8000, 20000];

type Active =
  | { kind: "conversation"; connectionId: number; name: string; startSample: number }
  | { kind: "voice_note"; startSample: number };

export interface Clip {
  id: number;
  kind: "conversation" | "voice_note";
  label: string;
  seconds: number;
  status: "uploading" | "sent" | "refused" | "failed";
  message?: string;
}

export interface MicState {
  on: boolean;
  starting: boolean;
  active: null | { kind: Active["kind"]; name?: string; seconds: number; limit: number };
  /** The latest thing worth telling the person ("Tapped Bob: not recorded…"). */
  notice: string | null;
  clips: Clip[];
  level: number;
}

export interface UploadParams {
  kind: "conversation" | "voice_note";
  connectionId?: number;
  startedAt?: number;
}

export interface ControllerDeps {
  source: AudioSource;
  eventId: number;
  connections: (eventId: number) => Promise<Connection[]>;
  upload: (eventId: number, wav: Blob, params: UploadParams) => Promise<unknown>;
  /** Timers, swappable in tests. */
  setInterval?: (fn: () => void, ms: number) => unknown;
  clearInterval?: (id: unknown) => void;
  sleep?: (ms: number) => Promise<void>;
}

const firstName = (name: string) => name.trim().split(/\s+/)[0] || name;

export class PhoneMicController {
  private deps: ControllerDeps;
  private seen = new Set<number>();
  private seeded = false;
  private active: Active | null = null;
  private timers: unknown[] = [];
  private listeners = new Set<(s: MicState) => void>();
  private nextClipId = 1;
  private _state: MicState = { on: false, starting: false, active: null, notice: null, clips: [], level: 0 };

  constructor(deps: ControllerDeps) {
    this.deps = deps;
  }

  get state(): MicState {
    return this._state;
  }

  subscribe(fn: (s: MicState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<MicState>) {
    this._state = { ...this._state, ...patch };
    this.listeners.forEach((fn) => fn(this._state));
  }

  private get store() {
    return this.deps.source.store;
  }

  private seconds(fromSample: number, toSample = this.store.end) {
    return (toSample - fromSample) / SAMPLE_RATE;
  }

  /** Call from a tap/click (iOS only starts audio from a user gesture). */
  async start(): Promise<void> {
    if (this._state.on || this._state.starting) return;
    this.set({ starting: true, notice: null });
    try {
      await this.deps.source.start();
    } catch (err) {
      this.set({ starting: false, notice: micErrorMessage(err) });
      throw err;
    }
    // Taps from before the mic was on aren't recorded.
    await this.poll();
    const every = this.deps.setInterval ?? ((fn, ms) => window.setInterval(fn, ms));
    this.timers = [every(() => void this.poll(), POLL_MS), every(() => this.tick(), TICK_MS)];
    this.set({ on: true, starting: false });
  }

  /** Turn the mic off. A conversation in progress is saved first. */
  stop(): void {
    if (this.active) this.finish(this.store.end);
    const clear = this.deps.clearInterval ?? ((id) => window.clearInterval(id as number));
    this.timers.forEach(clear);
    this.timers = [];
    this.deps.source.stop();
    this.seeded = false;
    this.set({ on: false, starting: false, active: null, level: 0 });
  }

  endConversation(): void {
    if (this.active?.kind === "conversation") this.finish(this.store.end);
  }

  toggleVoiceNote(): void {
    if (!this._state.on) return;
    if (this.active?.kind === "voice_note") {
      this.finish(this.store.end);
      return;
    }
    if (this.active) this.finish(this.store.end); // like the bracelet: a click ends the conversation
    this.active = { kind: "voice_note", startSample: this.store.end };
    this.set({ notice: null });
    this.tick();
  }

  async poll(): Promise<void> {
    let list: Connection[];
    try {
      list = await this.deps.connections(this.deps.eventId);
    } catch {
      return; // try again next time (the server may be waking up)
    }
    this.handleConnections(list);
  }

  /** New taps in the connections list. Public for tests. */
  handleConnections(list: Connection[]): void {
    const fresh = list.filter((c) => c.connection_id != null && !this.seen.has(c.connection_id));
    fresh.forEach((c) => this.seen.add(c.connection_id!));
    if (!this.seeded) {
      this.seeded = true;
      if (list.length && list.every((c) => c.connection_id == null)) {
        this.set({ notice: "The trO server needs an update before the phone mic can record conversations." });
      }
      return;
    }
    if (!fresh.length) return;
    const newest = fresh.reduce((a, b) => (Date.parse(b.tapped_at) > Date.parse(a.tapped_at) ? b : a));

    // The tap happened a moment before we heard about it: cut there.
    const cut = Math.max(this.store.first, this.store.end - PREROLL_S * SAMPLE_RATE, this.active?.startSample ?? 0);
    if (this.active) this.finish(cut);

    if (newest.both_consented) {
      this.active = { kind: "conversation", connectionId: newest.connection_id!, name: newest.name, startSample: cut };
      this.set({ notice: null });
    } else {
      this.set({ notice: `Tapped ${firstName(newest.name)}. Not recording: one of you said no to recording.` });
    }
    this.tick();
  }

  /** Limits, memory and the on-screen timer. Public for tests. */
  tick(): void {
    const a = this.active;
    if (a) {
      const limit = a.kind === "conversation" ? MAX_CONVERSATION_S : MAX_VOICE_NOTE_S;
      if (this.seconds(a.startSample) >= limit) {
        this.finish(a.startSample + limit * SAMPLE_RATE);
        this.set({
          notice: a.kind === "conversation" ? "Stopped at the 3-minute limit. Saved." : "Voice notes stop at 30 seconds. Saved.",
        });
      } else {
        this.store.trimBefore(a.startSample);
      }
    }
    if (!this.active) this.store.trimBefore(this.store.end - (PREROLL_S + 1) * SAMPLE_RATE);
    const now = this.active;
    this.set({
      level: this.deps.source.level,
      active: now
        ? {
            kind: now.kind,
            name: now.kind === "conversation" ? now.name : undefined,
            seconds: Math.floor(this.seconds(now.startSample)),
            limit: now.kind === "conversation" ? MAX_CONVERSATION_S : MAX_VOICE_NOTE_S,
          }
        : null,
    });
  }

  /** Cut the active clip at `endSample` and upload it. */
  private finish(endSample: number): void {
    const a = this.active;
    this.active = null;
    this.set({ active: null });
    if (!a) return;
    const samples = this.store.slice(a.startSample, endSample);
    const seconds = samples.length / SAMPLE_RATE;
    if (seconds < MIN_CLIP_S) return;
    const clip: Clip = {
      id: this.nextClipId++,
      kind: a.kind,
      label: a.kind === "conversation" ? `Conversation with ${firstName(a.name)}` : "Voice note",
      seconds: Math.round(seconds),
      status: "uploading",
    };
    this.set({ clips: [clip, ...this._state.clips].slice(0, 20) });
    const params: UploadParams = {
      kind: a.kind,
      connectionId: a.kind === "conversation" ? a.connectionId : undefined,
      startedAt: this.store.wallMsAt(a.startSample) ?? undefined,
    };
    void this.send(clip.id, encodeWav(samples), params);
  }

  private updateClip(id: number, patch: Partial<Clip>) {
    this.set({ clips: this._state.clips.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
  }

  private async send(clipId: number, wav: Blob, params: UploadParams): Promise<void> {
    const sleep = this.deps.sleep ?? ((ms) => new Promise<void>((r) => setTimeout(r, ms)));
    let last = "Couldn't upload this clip.";
    for (const wait of RETRY_DELAYS_MS) {
      if (wait) await sleep(wait);
      try {
        await this.deps.upload(this.deps.eventId, wav, params);
        this.updateClip(clipId, { status: "sent", message: "Sent. Notes show up on your dashboard in a minute." });
        return;
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) {
          this.updateClip(clipId, { status: "refused", message: "Not kept: one of you turned recording off." });
          return;
        }
        if (err instanceof ApiError && err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429) {
          this.updateClip(clipId, { status: "failed", message: err.message });
          return;
        }
        last = err instanceof ApiError ? err.message : last;
      }
    }
    this.updateClip(clipId, { status: "failed", message: last });
  }
}

export function micErrorMessage(err: unknown): string {
  const name = (err as { name?: string } | null)?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return "trO needs the microphone. Allow it in your browser’s settings for this site, then try again.";
  if (name === "NotFoundError") return "This phone has no microphone trO can use.";
  if (typeof navigator !== "undefined" && !navigator.mediaDevices?.getUserMedia)
    return "This browser can’t record. Open trO in Safari or Chrome over https.";
  return "Couldn’t start the microphone. Try again.";
}

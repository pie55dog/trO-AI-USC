/**
 * Phone mic (/e/:eventId/mic): the phone records conversations until the
 * bracelets have their own mics. The bracelet still does the tap; this page
 * notices the new connection and records it (see phoneMic/controller.ts).
 *
 * The page has to stay open with the screen on: phones stop web audio when
 * locked. We ask for a screen wake lock where the browser supports it.
 */

import { ArrowLeft, Mic, MicOff, Square, Watch } from "lucide-react";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, tokenStore, type Me } from "../api";
import { Button, Card, cx, DisplayTitle, ErrorNote, Icon, IconBubble, Screen, StatusPill } from "../components/ui";
import { useEventContext } from "../hooks";
import { MicCapture } from "../phoneMic/audio";
import { PhoneMicController, type Clip, type MicState } from "../phoneMic/controller";
import { Badge } from "./EventHome";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Keep the screen awake while the mic is on (where the browser allows it). */
function useWakeLock(on: boolean): boolean | null {
  const [supported, setSupported] = useState<boolean | null>(null);
  useEffect(() => {
    if (!on) return;
    const wl = (navigator as Navigator & { wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> } }).wakeLock;
    if (!wl) {
      setSupported(false);
      return;
    }
    let lock: { release(): Promise<void> } | null = null;
    let alive = true;
    const grab = () => {
      if (document.visibilityState !== "visible") return;
      wl.request("screen").then(
        (l) => (alive ? (lock = l) : void l.release()),
        () => setSupported(false),
      );
    };
    setSupported(true);
    grab();
    document.addEventListener("visibilitychange", grab); // the lock drops whenever the page is hidden
    return () => {
      alive = false;
      document.removeEventListener("visibilitychange", grab);
      void lock?.release().catch(() => undefined);
    };
  }, [on]);
  return supported;
}

export function useController(eventId: number | null, make?: (eventId: number) => PhoneMicController) {
  const controller = useMemo(
    () =>
      eventId
        ? (make ?? ((id) =>
            new PhoneMicController({
              source: new MicCapture(),
              eventId: id,
              connections: api.connections,
              upload: api.uploadRecording,
            })))(eventId)
        : null,
    [eventId, make],
  );
  const state = useSyncExternalStore(
    (fn) => controller?.subscribe(fn) ?? (() => undefined),
    () => controller?.state ?? null,
  );
  // Leaving the page turns the mic off (and saves a conversation in progress).
  useEffect(() => () => controller?.stop(), [controller]);
  return { controller, state };
}

export default function PhoneMic({ makeController }: { makeController?: (eventId: number) => PhoneMicController }) {
  const { eventId } = useEventContext();
  const [me, setMe] = useState<Me | null>(null);
  const { controller, state } = useController(eventId, makeController);
  const wakeLock = useWakeLock(Boolean(state?.on));
  const [wasHidden, setWasHidden] = useState(false);

  useEffect(() => {
    if (tokenStore.get()) api.me().then(setMe, () => undefined);
  }, []);

  // Phones pause web audio when the screen is off; tell the person when they come back.
  useEffect(() => {
    if (!state?.on) return;
    const onChange = () => document.visibilityState === "hidden" && setWasHidden(true);
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, [state?.on]);

  // Ask before closing the tab mid-conversation.
  const recording = Boolean(state?.active);
  useEffect(() => {
    if (!recording) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [recording]);

  if (!eventId) return <Navigate to="/" replace />;
  if (!tokenStore.get()) return <Navigate to={`/e/${eventId}`} replace />;
  if (!controller || !state) return null;

  const consentOff = me?.preferences.recording_consent === false;

  return (
    <Screen className="gap-6 pt-[31px] pb-10">
      <section className="relative flex flex-col gap-4">
        <Link to={`/e/${eventId}`} className="flex min-h-11 items-center gap-2 self-start text-label text-highlight">
          <Icon icon={ArrowLeft} />
          Your connections
        </Link>
        <StatusPill icon={<Icon icon={Watch} />}>Bracelet taps · phone listens</StatusPill>
        <DisplayTitle>Phone mic.</DisplayTitle>
        <p className="text-body text-highlight">
          Until the bracelets have their own mics, your phone records. Tap bracelets like normal: when you both said yes to
          recording, trO records that conversation and turns it into notes. Keep this page open with the phone in your hand
          or front pocket.
        </p>
      </section>

      {consentOff && (
        <Card className="p-5 text-body text-highlight">
          You said no to recording, so only voice notes work here.{" "}
          <Link to={`/e/${eventId}/preferences`} className="font-semibold underline">
            Change preferences
          </Link>
        </Card>
      )}

      <MicPanel state={state} controller={controller} />

      {state.on && wakeLock === false && (
        <p role="status" className="text-caption text-highlight/70">
          This browser can’t keep the screen on. Set Auto-Lock to Never while you use the phone mic: a locked phone stops
          recording.
        </p>
      )}
      {state.on && wasHidden && (
        <p role="status" className="text-caption text-highlight/70">
          The screen went off, so recording paused for that time. Keep this page open to record.
        </p>
      )}

      {state.clips.length > 0 && <ClipList clips={state.clips} />}

      <p className="text-caption text-highlight/50">
        Audio goes only to trO’s server, is deleted as soon as it’s transcribed, and is never kept if either of you said no.
        Each new tap ends the last conversation; recordings stop after 3 minutes.
      </p>
    </Screen>
  );
}

function MicPanel({ state, controller }: { state: MicState; controller: PhoneMicController }) {
  const [error, setError] = useState<string | null>(null);
  const start = () => {
    setError(null);
    controller.start().catch(() => setError(controller.state.notice));
  };

  if (!state.on)
    return (
      <Card className="flex flex-col gap-4 p-5">
        <div className="flex items-start gap-3">
          <IconBubble tone="maroon">
            <Icon icon={MicOff} size={20} />
          </IconBubble>
          <div className="flex flex-col gap-0.5">
            <p className="text-label font-medium text-highlight">Mic is off</p>
            <p className="text-caption text-highlight/70">Nothing is recorded until you turn it on.</p>
          </div>
        </div>
        <Button type="button" onClick={start} loading={state.starting} arrow={false} leading={<Icon icon={Mic} />}>
          Turn on phone mic
        </Button>
        {error && <ErrorNote>{error}</ErrorNote>}
      </Card>
    );

  const a = state.active;
  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-start gap-3">
        <span aria-hidden className="relative mt-1.5 flex size-3 shrink-0">
          {a && <span className="absolute inline-flex size-full animate-ping rounded-full bg-yellow opacity-75" />}
          <span className={cx("relative inline-flex size-3 rounded-full", a ? "bg-yellow" : "bg-highlight/40")} />
        </span>
        <div className="flex flex-1 flex-col gap-0.5" role="status" aria-live="polite">
          <p className="text-label font-medium text-highlight">
            {a ? (a.kind === "conversation" ? `Recording with ${a.name}` : "Recording a voice note") : "Listening for your next tap"}
          </p>
          <p className="text-caption text-highlight/70 tabular-nums">
            {a ? `${clock(a.seconds)} of ${clock(a.limit)}` : "Hold your bracelet to someone else’s to start."}
          </p>
        </div>
      </div>

      <div aria-hidden className="h-1.5 w-full overflow-hidden rounded-full bg-highlight/10">
        <div className="h-full rounded-full bg-yellow transition-[width] duration-200" style={{ width: `${Math.round(state.level * 100)}%` }} />
      </div>

      {state.notice && <p className="text-caption text-highlight">{state.notice}</p>}

      <div className="flex flex-col gap-2">
        {a?.kind === "conversation" && (
          <Button type="button" onClick={() => controller.endConversation()} arrow={false} leading={<Icon icon={Square} />}>
            End conversation
          </Button>
        )}
        <Button type="button" variant="soft" onClick={() => controller.toggleVoiceNote()} arrow={false} leading={<Icon icon={Mic} />}>
          {a?.kind === "voice_note" ? "Stop voice note" : "Record a voice note"}
        </Button>
        <button type="button" onClick={() => controller.stop()} className="min-h-11 text-label text-highlight/70 underline">
          Turn off phone mic
        </button>
      </div>
    </Card>
  );
}

const CLIP_BADGE: Record<Clip["status"], [string, "yellow" | "glass"]> = {
  uploading: ["Sending…", "glass"],
  sent: ["Sent", "yellow"],
  refused: ["Not kept", "glass"],
  failed: ["Failed", "glass"],
};

function ClipList({ clips }: { clips: Clip[] }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-title font-semibold text-highlight">Recorded</h2>
      <Card className="flex flex-col gap-4 p-5">
        {clips.map((c) => (
          <div key={c.id} className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-0.5">
              <p className="text-label font-medium text-highlight">
                {c.label} <span className="text-highlight/50 tabular-nums">· {clock(c.seconds)}</span>
              </p>
              {c.message && <p className="text-caption text-highlight/70">{c.message}</p>}
            </div>
            <Badge tone={CLIP_BADGE[c.status][1]}>{CLIP_BADGE[c.status][0]}</Badge>
          </div>
        ))}
      </Card>
    </section>
  );
}

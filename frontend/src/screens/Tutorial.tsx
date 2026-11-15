/**
 * How it works: five pages a new person sees after tapping their bracelet,
 * then step 1. Also reachable from the dashboard's Tutorial button.
 * Figma (Page 1, "final"): "Onboarding 1 / Welcome" through "Onboarding 5 /
 * After the event" (Dark).
 *
 * Steps 1-3 each play a looping 3D animation, exported from the video fills
 * of the "Placeholder · 3D animation / …" frames in those Figma screens. Each
 * fills the content width at the Figma height (tap 316px, the other two 263px)
 * and crops like Figma's "Fill" scale mode.
 */

import { ChevronLeft, Mail, RotateCcw, Watch } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { tokenStore } from "../api";
import { Button, cx, DisplayTitle, Icon, IconBubble, Screen, StatusPill } from "../components/ui";
import { useEventContext } from "../hooks";
import recordingLightPoster from "../assets/animations/recording-light-poster.jpg";
import recordingLightMp4 from "../assets/animations/recording-light.mp4";
import recordingLightWebm from "../assets/animations/recording-light.webm";
import tapPoster from "../assets/animations/tap-poster.jpg";
import tapMp4 from "../assets/animations/tap.mp4";
import tapWebm from "../assets/animations/tap.webm";
import voiceNotePoster from "../assets/animations/voice-note-poster.jpg";
import voiceNoteMp4 from "../assets/animations/voice-note.mp4";
import voiceNoteWebm from "../assets/animations/voice-note.webm";

const PAGES = 5;

/**
 * A looping 3D animation. Muted + playsInline so phones (iOS Safari included)
 * autoplay it inline instead of going fullscreen. H.264 MP4 first (iOS, Chrome),
 * VP9 WebM for browsers without H.264. `data-animation` names the slot.
 */
function Animation({ name, mp4, webm, poster, height }: { name: string; mp4: string; webm: string; poster: string; height: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    // React sets `muted` as a property only, and some browsers check it before
    // allowing autoplay, so set it and nudge playback explicitly.
    const video = ref.current;
    if (!video) return;
    video.muted = true;
    video.play?.()?.catch(() => {});
  }, [mp4]);
  return (
    <video
      ref={ref}
      data-animation={name}
      aria-hidden
      poster={poster}
      autoPlay
      loop
      muted
      playsInline
      preload="auto"
      disablePictureInPicture
      className="block w-full object-cover"
      style={{ height }}
    >
      <source src={mp4} type="video/mp4" />
      <source src={webm} type="video/webm" />
    </video>
  );
}

/** trO/Step badge + yellow title. */
function StepTitle({ n, children }: { n: number; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-2xl bg-highlight/20 text-label font-medium text-yellow">
        {n}
      </span>
      <h1 className="text-title font-semibold text-yellow">
        <span className="sr-only">Step {n}: </span>
        {children}
      </h1>
    </div>
  );
}

function InfoCard({ icon, title, note }: { icon: ReactNode; title: string; note: string }) {
  return (
    <div className="glass flex items-start gap-3 rounded-[20px] bg-[rgb(27_24_25/0.6)] p-5">
      <IconBubble tone="maroon">{icon}</IconBubble>
      <div className="flex flex-col gap-0.5">
        <p className="text-label font-medium text-highlight">{title}</p>
        <p className="text-caption text-highlight/50">{note}</p>
      </div>
    </div>
  );
}

export default function Tutorial() {
  const navigate = useNavigate();
  const { eventId, eventName } = useEventContext();
  const [page, setPage] = useState(0);

  // No account yet: on to step 1. The dashboard sends anyone half set up to the right step.
  const done = () => navigate(tokenStore.get() ? `/e/${eventId}` : `/e/${eventId}/welcome`);
  const next = () => (page < PAGES - 1 ? setPage(page + 1) : done());
  const last = page === PAGES - 1;

  return (
    <Screen backdrop="stripes" className={cx("gap-8 pb-[34px]", page === 0 ? "pt-7" : "pt-4")}>
      {/* Onboarding 1 only: a soft band under the top bar. */}
      {page === 0 && (
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-10 h-[110px] bg-gradient-to-b from-dark/0 via-dark/80 to-dark/0" />
      )}

      <div className="relative flex items-center gap-4">
        <button
          type="button"
          aria-label="Back"
          onClick={() => setPage(page - 1)}
          disabled={page === 0}
          className={cx("glass flex size-10 shrink-0 items-center justify-center rounded-[20px] bg-highlight/[0.08] text-highlight", page === 0 && "invisible")}
        >
          <Icon icon={ChevronLeft} size={20} />
        </button>
        <div aria-label={`Page ${page + 1} of ${PAGES}`} role="progressbar" aria-valuemin={1} aria-valuemax={PAGES} aria-valuenow={page + 1} className="flex h-1 flex-1 gap-1.5">
          {Array.from({ length: PAGES }, (_, i) => (
            <span key={i} className={cx("h-1 flex-1 rounded-sm bg-highlight", i > page && "opacity-50")} />
          ))}
        </div>
        {last ? (
          <span className="text-label font-medium text-highlight/70">
            {PAGES} of {PAGES}
          </span>
        ) : (
          <button type="button" onClick={done} className="flex h-10 items-center text-label font-medium text-highlight/50">
            Skip
          </button>
        )}
      </div>

      {page === 0 && (
        <section className="relative flex flex-col gap-4">
          <StatusPill icon={<Icon icon={Watch} className="text-yellow" />}>How it works · 1 min</StatusPill>
          <DisplayTitle>Welcome to {eventName}.</DisplayTitle>
          <div className="flex flex-col gap-2 text-highlight">
            <h2 className="text-title font-semibold">This is trO</h2>
            <p className="text-body">
              A smart wristband that helps you keep your connections with the Trojan family. After the event you’ll get
              an email with everyone you met, ways to follow up, and any notes you took, without taking out your phone.
            </p>
          </div>
        </section>
      )}

      {page === 1 && (
        <section className="flex flex-col gap-4">
          <StepTitle n={1}>When you meet someone, tap bracelets</StepTitle>
          <p className="text-body text-highlight">
            Hold them together for about a second. Both buzz, and you’re added to each other’s follow-up lists.
          </p>
          <Animation name="tap" mp4={tapMp4} webm={tapWebm} poster={tapPoster} height={316} />
        </section>
      )}

      {page === 2 && (
        <section className="flex flex-col gap-4">
          <StepTitle n={2}>Get insights</StepTitle>
          <p className="text-body text-highlight">
            If you’ve both consented to recording, you’ll see this blinking light. <strong className="font-semibold">trO</strong> is
            taking notes on your conversation. If either of you said no, it only swaps contact info.
          </p>
          <Animation name="recording-light" mp4={recordingLightMp4} webm={recordingLightWebm} poster={recordingLightPoster} height={263} />
        </section>
      )}

      {page === 3 && (
        <section className="flex flex-col gap-4">
          <StepTitle n={3}>Reflect</StepTitle>
          <p className="text-body text-highlight">
            Press the button and say a note about anyone or any idea. <strong className="font-semibold">trO</strong> sorts it
            to the right person and sends it to you after the event.
          </p>
          <Animation name="voice-note" mp4={voiceNoteMp4} webm={voiceNoteWebm} poster={voiceNotePoster} height={263} />
        </section>
      )}

      {page === 4 && (
        <section className="flex flex-col gap-4">
          <h1 className="text-title font-semibold text-yellow">Before you go</h1>
          <InfoCard
            icon={<Icon icon={RotateCcw} size={20} />}
            title="After the event, return your bracelet to the staff."
            note="Drop it off at check-in on your way out."
          />
          <InfoCard
            icon={<Icon icon={Mail} size={20} />}
            title="Check your inbox 2h after the event."
            note="One email with everyone you met and how to follow up."
          />
        </section>
      )}

      <div className="mt-auto pt-2 pb-6">
        <Button className="w-full" onClick={next}>
          {page === 0 ? "Show me how" : last ? "Got it, I’m ready" : "Next"}
        </Button>
      </div>
    </Screen>
  );
}

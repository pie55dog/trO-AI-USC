/**
 * How it works: five pages a new person sees after tapping their bracelet,
 * then step 1. Also reachable from the dashboard's Tutorial button.
 * Figma (Page 1, "final"): "Onboarding 1 / Welcome" through "Onboarding 5 /
 * After the event" (Dark).
 *
 * The cream circles are deliberate placeholders (40% opacity in Figma): the
 * team is dropping a 3D animation into each one. Keep their sizes and
 * positions as in Figma.
 */

import { ChevronLeft, Mail, RotateCcw, Watch } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { tokenStore } from "../api";
import { Button, cx, DisplayTitle, Icon, IconBubble, Screen, StatusPill } from "../components/ui";
import { useEventContext } from "../hooks";

const PAGES = 5;

/** A circle reserved for a 3D animation. `data-animation` names the slot. */
function Placeholder({ name, size, className }: { name: string; size: number; className?: string }) {
  return (
    <div
      data-animation={name}
      aria-hidden
      className={cx("rounded-full bg-highlight", className)}
      style={{ width: size, height: size }}
    />
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
          {/* Two overlapping circles: 242px at left -88px, 263px at left 133px / top 166px. */}
          <div className="relative h-[429px] w-full overflow-hidden opacity-40">
            <Placeholder name="tap-a" size={242} className="absolute top-0 left-[-88px]" />
            <Placeholder name="tap-b" size={263} className="absolute top-[166px] left-[133px]" />
          </div>
        </section>
      )}

      {page === 2 && (
        <section className="flex flex-col gap-4">
          <StepTitle n={2}>Get insights</StepTitle>
          <p className="text-body text-highlight">
            If you’ve both consented to recording, you’ll see this blinking light. <strong className="font-semibold">trO</strong> is
            taking notes on your conversation. If either of you said no, it only swaps contact info.
          </p>
          <Placeholder name="recording-light" size={263} className="mx-auto opacity-40" />
        </section>
      )}

      {page === 3 && (
        <section className="flex flex-col gap-4">
          <StepTitle n={3}>Reflect</StepTitle>
          <p className="text-body text-highlight">
            Press the button and say a note about anyone or any idea. <strong className="font-semibold">trO</strong> sorts it
            to the right person and sends it to you after the event.
          </p>
          <Placeholder name="voice-note" size={263} className="mx-auto opacity-40" />
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

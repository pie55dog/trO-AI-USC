/**
 * "This is trO": how the bracelet works.
 * Figma: "Refined / This is trO" (node 28:47).
 *
 * The gray circles are deliberate placeholders: the team is dropping a 3D
 * animation into each one. Keep their sizes and positions as in Figma.
 */

import { Mail, RotateCcw, Watch } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { DisplayTitle, IconBubble, PrimaryButton, Screen, StatusPill, StickyCta } from "../components/ui";
import { useEventContext } from "../hooks";

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-body font-semibold text-white">
          {n}
        </span>
        <h2 className="text-title font-semibold">
          <span className="sr-only">Step {n}: </span>
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

/** A gray circle reserved for a 3D animation. `data-animation` names the slot. */
function Placeholder({ name, size, className }: { name: string; size: number; className?: string }) {
  return (
    <div
      data-animation={name}
      aria-hidden
      className={`rounded-full bg-placeholder ${className ?? ""}`}
      style={{ width: size, height: size }}
    />
  );
}

export default function Tutorial() {
  const navigate = useNavigate();
  const { eventId, eventName } = useEventContext();

  return (
    // overflow-x-clip: the first circle bleeds off the left edge as in Figma.
    <Screen className="gap-12 overflow-x-clip">
      <section className="flex flex-col gap-4">
        <StatusPill icon={<Watch />}>How it works · 1 min read</StatusPill>
        <DisplayTitle>
          Welcome to
          <br />
          {eventName}.
        </DisplayTitle>
        <div className="flex flex-col gap-2">
          <h2 className="text-title font-semibold">This is trO</h2>
          <p className="text-body text-ink-body">
            A smart wristband that helps you keep your connections with the Trojan family. After the event you’ll get an
            email with everyone you met, ways to follow up, and any notes you took, without taking out your phone.
          </p>
        </div>
      </section>

      <Step n={1} title="When you meet someone, tap bracelets">
        <p className="text-body text-ink-body">
          Hold them together for about a second. Both buzz, and you’re added to each other’s follow-up lists.
        </p>
        {/* Two overlapping circles: 242px at left -88px, 263px at left 133px / top 166px (Figma 28:59). */}
        {/* Clipped to the content width, as in the Figma frame. */}
        <div className="relative h-[429px] w-full overflow-hidden">
          <Placeholder name="tap-a" size={242} className="absolute top-0 left-[-88px]" />
          <Placeholder name="tap-b" size={263} className="absolute top-[166px] left-[133px]" />
        </div>
      </Step>

      <Step n={2} title="Get insights">
        <p className="text-body text-ink-body">
          If you’ve both consented to recording, you’ll see this blinking light. trO is taking notes on your
          conversation. If either of you said no, it only swaps contact info.
        </p>
        <Placeholder name="recording-light" size={263} className="mx-auto" />
      </Step>

      <Step n={3} title="Reflect">
        <p className="text-body text-ink-body">
          Press the button and say a note about anyone or any idea. trO sorts it to the right person and sends it to you
          after the event.
        </p>
        <Placeholder name="voice-note" size={263} className="mx-auto" />
      </Step>

      <section className="flex flex-col gap-3 rounded-[20px] border border-line p-5">
        <div className="flex items-start gap-3">
          <IconBubble>
            <RotateCcw />
          </IconBubble>
          <div className="flex flex-col gap-0.5">
            <p className="text-body font-semibold">After the event, return your bracelet to the staff.</p>
            <p className="text-caption text-ink-muted">Drop it off at check-in on your way out.</p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <IconBubble>
            <Mail />
          </IconBubble>
          <div className="flex flex-col gap-0.5">
            <p className="text-body font-semibold">Check your inbox the next morning.</p>
            <p className="text-caption text-ink-muted">One email with everyone you met and how to follow up.</p>
          </div>
        </div>
      </section>

      <StickyCta>
        <PrimaryButton onClick={() => navigate(`/e/${eventId}`)}>Got it, I’m ready</PrimaryButton>
      </StickyCta>
    </Screen>
  );
}

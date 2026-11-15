/**
 * Demo hub (/demo): one place to open every screen of the flow, for phone
 * testing and walking judges through it. On a preview build (no backend) it
 * is also the home page, since there is no bracelet to tap.
 */

import { BookOpen, ChevronRight, LayoutList, RotateCcw, SlidersHorizontal, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PREVIEW, storageSet, tokenStore } from "../api";
import { Button, DisplayTitle, IconBubble, Screen } from "../components/ui";
import { lastEventStore } from "../session";

/** Event used by the demo links; the bracelet tap link carries the real one. */
export const DEMO_EVENT = 1;

const SCREENS: { step: string; title: string; detail: string; to: string; icon: ReactNode }[] = [
  {
    step: "Start",
    title: "How it works",
    detail: "How tapping, recording and voice notes work.",
    to: `/e/${DEMO_EVENT}/tutorial`,
    icon: <BookOpen />,
  },
  {
    step: "Step 1",
    title: "Welcome",
    detail: "Summary email and the profile your connections get.",
    to: `/e/${DEMO_EVENT}/welcome`,
    icon: <UserRound />,
  },
  {
    step: "Step 2",
    title: "Set your preferences",
    detail: "Recording consent and recommendations. Needs step 1 first.",
    to: `/e/${DEMO_EVENT}/preferences`,
    icon: <SlidersHorizontal />,
  },
  {
    step: "During the event",
    title: "Your connections",
    detail: "Everyone you tapped. Needs steps 1 and 2 first.",
    to: `/e/${DEMO_EVENT}`,
    icon: <LayoutList />,
  },
];

export default function Demo() {
  const navigate = useNavigate();

  const startOver = () => {
    // Sign out and forget everything this phone saved, then begin at the start.
    tokenStore.set(null);
    for (const key of ["tro.preview", "tro.profileDraft", "tro.returnTo", `tro.bracelet.${DEMO_EVENT}`]) storageSet(key, null);
    lastEventStore.set(DEMO_EVENT);
    navigate(SCREENS[0].to);
  };

  return (
    <Screen className="gap-8 pt-12 pb-12">
      <header className="relative flex flex-col gap-2">
        <DisplayTitle>trO demo</DisplayTitle>
        <p className="text-body text-highlight">
          Open any screen of the flow. In real use, tapping the bracelet opens how it works.
          {PREVIEW && " This preview has no server, so what you enter stays on this phone."}
        </p>
      </header>

      <nav aria-label="Screens" className="flex flex-col gap-3">
        {SCREENS.map((s) => (
          <Link
            key={s.to}
            to={s.to}
            className="glass flex min-h-[72px] items-center gap-4 rounded-[20px] p-4 active:bg-highlight/10"
          >
            <IconBubble>{s.icon}</IconBubble>
            <span className="flex flex-1 flex-col gap-0.5">
              <span className="text-caption text-yellow">{s.step}</span>
              <span className="text-label font-medium text-highlight">{s.title}</span>
              <span className="text-caption text-highlight/70">{s.detail}</span>
            </span>
            <ChevronRight aria-hidden strokeWidth={1} absoluteStrokeWidth className="size-5 text-highlight/70" />
          </Link>
        ))}
      </nav>

      <div className="mt-auto flex">
        <Button type="button" variant="soft" arrow={false} className="flex-1" onClick={startOver} leading={<RotateCcw aria-hidden strokeWidth={1} absoluteStrokeWidth className="size-4" />}>
          Start over as a new person
        </Button>
      </div>
    </Screen>
  );
}

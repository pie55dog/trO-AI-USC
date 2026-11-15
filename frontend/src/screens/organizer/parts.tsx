/** Small pieces the organizer console shares, in the dark trO style. */

import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cx } from "../../components/ui";

/** Small soft pill for secondary actions (Copy link, Export CSV...). */
export const pillClass = (className?: string) =>
  cx(
    "flex min-h-11 shrink-0 items-center gap-1.5 rounded-full bg-highlight/10 px-4 text-caption font-medium text-highlight",
    "hover:bg-highlight/15 active:opacity-80 disabled:opacity-40",
    className,
  );

/** In-page spinner. The app's Loading covers the whole screen, which is too much inside a panel. */
export function InlineLoading({ label }: { label: string }) {
  return (
    <div role="status" className="flex items-center justify-center py-16 text-highlight/50">
      <LoaderCircle aria-hidden className="size-5 animate-spin" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** Glass card holding one task (attendee link, check-in desk...). */
export function Panel({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section className="glass flex flex-col gap-5 rounded-[20px] bg-highlight/[0.03] p-5 sm:p-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-title font-medium text-highlight">{title}</h2>
        {intro && <p className="max-w-[64ch] text-body text-highlight/60">{intro}</p>}
      </div>
      {children}
    </section>
  );
}

export const displayClass = "font-display text-display font-normal text-yellow";

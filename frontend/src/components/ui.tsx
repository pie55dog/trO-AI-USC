/**
 * Shared building blocks matching the "Tro / Components" frame in Figma:
 * Button/Primary, Button/Secondary, Chip, Field, plus the small pills and
 * icon bubbles that repeat across screens.
 */

import { ArrowRight, Check, LoaderCircle } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { useId } from "react";

function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/** Page column: 393px frames, 24px side margins, centered on bigger screens. */
export function Screen({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <main className={cx("mx-auto flex min-h-dvh w-full max-w-[440px] flex-col px-6 pt-4", className)}>
      {children}
    </main>
  );
}

/** Black, full-width, 49px tall. Shows a spinner while `loading`. */
export function PrimaryButton({
  children,
  loading,
  arrow = true,
  className,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; arrow?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "flex w-full items-center justify-center gap-2 rounded-[14px] bg-ink px-6 py-3.5 text-body font-semibold text-white transition-opacity",
        "disabled:opacity-40",
        className,
      )}
    >
      {children}
      {loading ? (
        <LoaderCircle aria-hidden className="size-4 animate-spin" />
      ) : (
        arrow && <ArrowRight aria-hidden className="size-4" />
      )}
    </button>
  );
}

export function SecondaryButton({ className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cx(
        "flex flex-1 items-center justify-center rounded-[14px] border border-tint bg-tint px-5 py-3.5 text-body font-semibold text-ink",
        "disabled:opacity-40",
        className,
      )}
    />
  );
}

/** Sticky bottom area for the main action, so it stays in the thumb zone. */
export function StickyCta({ children, divider }: { children: ReactNode; divider?: boolean }) {
  return (
    <div
      className={cx(
        "sticky bottom-0 -mx-6 mt-auto flex flex-col gap-2 bg-bg px-6 pt-4 pb-[max(24px,env(safe-area-inset-bottom))]",
        divider && "border-t border-line",
      )}
    >
      {children}
    </div>
  );
}

/** Gray rounded pill with a small icon (e.g. "Bracelet 042 linked to this phone"). */
export function StatusPill({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 self-start rounded-full bg-soft py-2 pr-3.5 pl-3 text-caption text-ink-body">
      <span aria-hidden className="flex size-4 items-center justify-center [&>svg]:size-4">
        {icon}
      </span>
      {children}
    </div>
  );
}

/** Round gray bubble behind an icon (preferences, tutorial "after the event"). */
export function IconBubble({ children }: { children: ReactNode }) {
  return (
    <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-full bg-soft [&>svg]:size-5">
      {children}
    </span>
  );
}

/** "Welcome to / event." in the 40px italic display style. */
export function DisplayTitle({ children }: { children: ReactNode }) {
  return <h1 className="text-display font-normal italic text-ink">{children}</h1>;
}

type FieldProps = {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  multiline?: boolean;
} & InputHTMLAttributes<HTMLInputElement> &
  TextareaHTMLAttributes<HTMLTextAreaElement>;

/** Label (12 semibold) + input (14, 12px radius) + optional hint or error. */
export function Field({ label, hint, error, multiline, className, ...rest }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const inputClass = cx(
    "w-full rounded-xl border bg-bg px-4 py-[13px] text-body text-ink placeholder:text-ink-muted",
    error ? "border-danger" : "border-line",
  );
  return (
    <div className={cx("flex min-w-0 flex-col gap-2", className)}>
      <label htmlFor={id} className="text-caption font-semibold text-ink">
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          rows={2}
          aria-describedby={hint || error ? hintId : undefined}
          aria-invalid={!!error}
          className={cx(inputClass, "resize-none")}
          {...(rest as TextareaHTMLAttributes<HTMLTextAreaElement>)}
        />
      ) : (
        <input
          id={id}
          aria-describedby={hint || error ? hintId : undefined}
          aria-invalid={!!error}
          className={inputClass}
          {...(rest as InputHTMLAttributes<HTMLInputElement>)}
        />
      )}
      {(error || hint) && (
        <p id={hintId} className={cx("text-caption", error ? "text-danger" : "text-ink-muted")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

/** Selectable chip: outlined when off, tinted with a check when on. */
export function Chip({
  selected,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      {...rest}
      className={cx(
        "flex min-h-11 items-center gap-1.5 rounded-full border py-3 text-caption whitespace-nowrap",
        selected
          ? "border-ink bg-tint pr-4 pl-3 font-semibold text-ink"
          : "border-line bg-bg px-4 text-ink-body",
        className,
      )}
    >
      {selected && <Check aria-hidden className="size-4" />}
      {children}
    </button>
  );
}

/** Two equal options ("No" / "Yes"); nothing is selected until the user picks. */
export function YesNo({
  value,
  onChange,
  label,
}: {
  value: boolean | null;
  onChange: (v: boolean) => void;
  label: string;
}) {
  const option = (v: boolean, text: string) => (
    <button
      type="button"
      role="radio"
      aria-checked={value === v}
      onClick={() => onChange(v)}
      className={cx(
        "flex min-h-11 flex-1 items-center justify-center rounded-xl border px-4 py-3 text-body font-semibold transition-colors",
        value === v ? "border-ink bg-ink text-white" : "border-line bg-bg text-ink",
      )}
    >
      {text}
    </button>
  );
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-2">
      {option(false, "No")}
      {option(true, "Yes")}
    </div>
  );
}

/** Inline error banner for failed requests. */
export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-xl border border-danger/30 bg-danger/5 px-4 py-3 text-caption text-danger">
      {children}
    </p>
  );
}

/** Centered spinner for loading states. */
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex flex-1 items-center justify-center py-24 text-ink-muted">
      <LoaderCircle aria-hidden className="size-6 animate-spin" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** Brand glyphs aren't in lucide-react, so these two use lucide's original paths. */
export function LinkedinIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
      <rect width="4" height="12" x="2" y="9" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

export function InstagramIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <rect width="20" height="20" x="2" y="2" rx="5" ry="5" />
      <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
      <line x1="17.5" x2="17.51" y1="6.5" y2="6.5" />
    </svg>
  );
}

/**
 * Shared building blocks matching the dark Figma screens (Page 4) and the
 * "trO UI Components" frame: glass Button, Info pill, Step badge, Field,
 * Chip, consent options, the top gradient band and the logo loader.
 */

import { ArrowRight, Check, LoaderCircle, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";
import bgStripes from "../assets/bg-stripes.png";
import topBand from "../assets/top-band.png";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/** Figma icons are 1px line icons; lucide drawn at the same weight. */
export function Icon({ icon: C, size = 16, className }: { icon: LucideIcon; size?: number; className?: string }) {
  return <C aria-hidden size={size} strokeWidth={1} absoluteStrokeWidth className={cx("shrink-0", className)} />;
}

/**
 * Page column: 393px frames, 25px side margins, centered on bigger screens.
 * `backdrop="top"`: near-black page with the blurred maroon band at the top
 * (setup and event screens). `backdrop="stripes"`: the full-bleed striped
 * gradient photo used behind the "How it works" pages.
 */
export function Screen({
  children,
  className,
  backdrop = "top",
}: {
  children: ReactNode;
  className?: string;
  backdrop?: "top" | "stripes" | "none";
}) {
  return (
    <main
      className={cx(
        "relative mx-auto flex min-h-dvh w-full max-w-[440px] flex-col overflow-x-clip bg-darkest px-[25px]",
        className,
      )}
      style={
        backdrop === "stripes"
          ? { backgroundImage: `url(${bgStripes})`, backgroundSize: "cover", backgroundPosition: "center" }
          : undefined
      }
    >
      {backdrop === "top" && <TopBand />}
      {children}
    </main>
  );
}

/** "trO/Top": 96px blurred brand band, fading into the page (Top + Top fade). */
export function TopBand() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-[97px]">
      <img src={topBand} alt="" className="absolute inset-x-0 top-0 h-24 w-full object-cover" />
      <div className="absolute inset-0 bg-gradient-to-b from-darkest/0 to-darkest" />
    </div>
  );
}

/**
 * trO/Button. "primary" is the frosted glass pill (white 20%), "soft" the
 * lighter one (white 10%) used for the photo actions.
 */
export function Button({
  children,
  loading,
  arrow = true,
  leading,
  variant = "primary",
  className,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  loading?: boolean;
  arrow?: boolean;
  leading?: ReactNode;
  variant?: "primary" | "soft";
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={buttonClass(variant, className)}
    >
      {leading}
      {children}
      {loading ? (
        <LoaderCircle aria-hidden className="size-4 animate-spin" />
      ) : (
        arrow && <Icon icon={ArrowRight} />
      )}
    </button>
  );
}

export function buttonClass(variant: "primary" | "soft" = "primary", className?: string) {
  return cx(
    "flex min-h-[45px] items-center justify-center gap-2 rounded-[50px] px-6 py-[14px] text-label font-medium whitespace-nowrap text-highlight transition-opacity",
    "disabled:opacity-40 active:opacity-80",
    variant === "primary" ? "glass bg-white/20" : "bg-white/10",
    className,
  );
}

/** Full-width primary button (kept for the existing call sites). */
export function PrimaryButton(props: Parameters<typeof Button>[0]) {
  return <Button {...props} className={cx("w-full", props.className)} />;
}

/** "Step 1 of 2" with two short bars (Figma "Step indicator"). */
export function StepIndicator({ step }: { step: 1 | 2 }) {
  return (
    <div className="flex items-center gap-1.5" aria-label={`Step ${step} of 2`}>
      <span className="text-caption text-highlight">Step {step} of 2</span>
      <span aria-hidden className="h-1 w-6 rounded-sm bg-highlight" />
      <span aria-hidden className="h-1 w-6 rounded-sm bg-highlight" />
    </div>
  );
}

/** Bottom area for the main action, so it stays in the thumb zone. */
export function StickyCta({ children, divider, sticky = true }: { children: ReactNode; divider?: boolean; sticky?: boolean }) {
  return (
    <div className={cx("mt-auto", sticky && "sticky bottom-0 -mx-[25px] bg-darkest px-[25px]")}>
      <div
        className={cx(
          "flex flex-col gap-2",
          divider ? "border-t border-highlight pt-4 pb-[max(32px,env(safe-area-inset-bottom))]" : "pt-2 pb-[max(24px,env(safe-area-inset-bottom))]",
        )}
      >
        {children}
      </div>
    </div>
  );
}

/** trO/Info pill: "Bracelet 042 linked", "How it works · 1 min". */
export function StatusPill({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <div className="inline-flex items-center gap-2 self-start rounded-full bg-highlight/20 py-2 pr-3.5 pl-3 text-caption text-highlight">
      {icon}
      {children}
    </div>
  );
}

/**
 * Round bubble behind an icon. "light": cream disc (preferences, LinkedIn);
 * "maroon": 30% maroon disc on the "Before you go" cards.
 */
export function IconBubble({ children, tone = "light" }: { children: ReactNode; tone?: "light" | "maroon" }) {
  return (
    <span
      aria-hidden
      className={cx(
        "flex size-10 shrink-0 items-center justify-center rounded-full [&>svg]:size-5",
        tone === "light" ? "bg-highlight text-dark" : "bg-maroon/30 text-highlight",
      )}
    >
      {children}
    </span>
  );
}

/** trO/Display: 40px Libertinus Sans in yellow ("Welcome to event."). */
export function DisplayTitle({ children }: { children: ReactNode }) {
  return <h1 className="font-display text-display font-normal text-yellow">{children}</h1>;
}

/** Glass card (20px radius) used for questions, connections and info rows. */
export function Card({ children, className, as: Tag = "section" }: { children: ReactNode; className?: string; as?: "section" | "article" | "div" }) {
  return <Tag className={cx("glass rounded-[20px]", className)}>{children}</Tag>;
}

export const inputClass = (error?: boolean) =>
  cx(
    "w-full min-w-0 rounded-xl border bg-highlight/[0.06] px-4 py-[13px] text-body text-highlight placeholder:text-highlight/45",
    error ? "border-danger" : "border-highlight/20",
  );

type FieldProps = {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
} & InputHTMLAttributes<HTMLInputElement>;

/** Label (12 semibold) + input (14, 12px radius) + optional hint or error. */
export function Field({ label, hint, error, className, ...rest }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className={cx("flex min-w-0 flex-col gap-2", className)}>
      <label htmlFor={id} className="text-label-s font-semibold text-highlight">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={hint || error ? hintId : undefined}
        aria-invalid={!!error}
        className={inputClass(!!error)}
        {...rest}
      />
      {(error || hint) && (
        <p id={hintId} className={cx("text-caption", error ? "text-danger" : "text-highlight/50")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

/** Interest chip: outlined cream when off, yellow with a check when on. */
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
        "flex min-h-10 items-center gap-1.5 rounded-full py-3 text-caption whitespace-nowrap",
        selected
          ? "bg-yellow pr-4 pl-3 font-semibold leading-[1.3] text-dark"
          : "border border-highlight bg-[rgb(27_24_25/0.2)] px-4 text-highlight",
        className,
      )}
    >
      {selected && <Icon icon={Check} className="text-dark" />}
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
        "flex min-h-11 flex-1 items-center justify-center rounded-xl border px-4 py-3 text-label font-medium transition-colors",
        value === v ? "border-highlight bg-highlight text-dark" : "border-highlight/50 bg-dark text-highlight",
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
    <p role="alert" className="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-caption text-danger">
      {children}
    </p>
  );
}

/**
 * Full-screen loading state: the trO logo animation from the Figma
 * "Loading" frames. The tip bounces in, the body draws, then "trO" slides in.
 */
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="fixed inset-0 z-10 flex items-center justify-center bg-dark">
      <span className="sr-only">{label}</span>
      <div aria-hidden className="flex items-start">
        <svg width="58" height="78" viewBox="0 0 58 78" fill="none" className="tro-logo-mark">
          <path
            className="tro-logo-tip"
            d="M9.13832 21.8101C8.95292 12.5745 5.46642 3.83702 3.40033 0C5.68264 3.24994 18.6887 8.43679 24.1552 8.85457C14.5599 11.7531 9.14268 22.0269 9.13832 21.8101Z"
            fill="#FDE872"
          />
          <path
            className="tro-logo-body"
            d="M10.5308 77.6281C-8.89812 22.0974 28.0306 -0.0874319 58.0002 7.28844C30.1339 5.3883 36.0056 29.0531 36.0056 29.0531C3.97807 27.6296 10.5308 77.6281 10.5308 77.6281Z"
            fill="#FDE872"
          />
        </svg>
        <TroWordmark className="tro-logo-word mt-3" />
      </div>
    </div>
  );
}

/** The "trO" letters from the logo (Figma "Loading" frame, 136x60). */
export function TroWordmark({ className }: { className?: string }) {
  return (
    <svg width="136" height="60" viewBox="0 0 136 60" fill="none" className={className} aria-hidden>
      <path
        d="M104.405 60C100.083 60 96.0411 59.2282 92.2803 57.6845C88.5475 56.1409 85.2919 54.036 82.5134 51.3697C79.7629 48.6754 77.5878 45.5461 75.9881 41.9817C74.4164 38.3893 73.6306 34.5583 73.6306 30.4888C73.6306 27.8226 73.9814 25.2545 74.683 22.7848C75.4127 20.315 76.4371 18.0136 77.7562 15.8806C79.0753 13.7476 80.661 11.811 82.5134 10.071C84.3938 8.30282 86.4706 6.8013 88.744 5.5664C91.0173 4.30345 93.4731 3.33518 96.1112 2.6616C98.7494 1.95995 101.514 1.60913 104.405 1.60913C107.295 1.60913 110.06 1.95995 112.698 2.6616C115.336 3.33518 117.792 4.30345 120.065 5.5664C122.367 6.8013 124.444 8.30282 126.296 10.071C128.148 11.811 129.734 13.7476 131.053 15.8806C132.4 18.0136 133.425 20.315 134.126 22.7848C134.856 25.2545 135.221 27.8226 135.221 30.4888C135.221 33.1831 134.856 35.7932 134.126 38.3192C133.425 40.817 132.4 43.1605 131.053 45.3496C129.734 47.5388 128.148 49.5314 126.296 51.3276C124.444 53.1239 122.367 54.6675 120.065 55.9585C117.792 57.2495 115.336 58.2459 112.698 58.9475C110.06 59.6492 107.295 60 104.405 60ZM104.405 57.2215C107.604 57.2215 110.425 56.5619 112.867 55.2428C115.336 53.8957 117.413 52.0293 119.097 49.6437C120.781 47.2581 122.044 44.4375 122.886 41.1819C123.756 37.9262 124.191 34.3619 124.191 30.4888C124.191 26.6438 123.756 23.1215 122.886 19.922C122.044 16.7225 120.781 13.9721 119.097 11.6707C117.413 9.34125 115.336 7.54504 112.867 6.28208C110.425 4.99106 107.604 4.34554 104.405 4.34554C101.149 4.34554 98.2863 4.99106 95.8165 6.28208C93.3748 7.54504 91.312 9.34125 89.628 11.6707C87.9722 13.9721 86.7232 16.7225 85.8813 19.922C85.0393 23.1215 84.6183 26.6438 84.6183 30.4888C84.6183 34.3619 85.0393 37.9262 85.8813 41.1819C86.7232 44.4375 87.9722 47.2581 89.628 49.6437C91.312 52.0293 93.3748 53.8957 95.8165 55.2428C98.2863 56.5619 101.149 57.2215 104.405 57.2215Z"
        fill="#FDE872"
      />
      <path
        d="M44.223 14.923L46.5312 14.094L46.8759 23.0798C47.5494 21.7888 48.8765 21.1152 49.8869 20.0487C50.8973 18.9822 52.0059 18.056 53.2127 17.2702C54.4476 16.4844 55.7386 15.881 57.0858 15.46C58.461 15.0109 59.8502 14.7864 61.2535 14.7864C62.5165 14.7864 63.7514 14.9548 64.9582 15.2916C66.1931 15.6284 67.3438 16.1616 68.4103 16.8913L65.716 24.0902C65.1547 23.4727 64.5653 22.9816 63.9478 22.6167C63.3304 22.2238 62.6989 21.9291 62.0534 21.7327C61.4079 21.5081 60.7483 21.3678 60.0748 21.3117C59.4012 21.2555 58.7276 21.2275 58.054 21.2275C56.9875 21.2275 55.9351 21.3818 54.8966 21.6906C53.8863 21.9993 52.918 22.4624 51.9918 23.0798C51.0657 23.6692 50.2096 24.441 49.4238 25.3952C48.638 26.3214 47.9504 27.416 47.361 28.6789L47.8707 58.6953H38.8149V17.1439L44.223 14.923Z"
        fill="#FDE872"
      />
      <path
        d="M13.5979 0.935238L16.0396 0V15.5856L25.6381 13.9275V19.2482H16.0396V49.6013C16.0396 50.2468 16.1519 50.8502 16.3764 51.4115C16.629 51.9729 16.9517 52.464 17.3447 52.885C17.7656 53.306 18.2568 53.6428 18.8181 53.8954C19.3794 54.1199 19.9969 54.2321 20.6704 54.2321C21.6247 54.2321 22.4947 53.9936 23.2806 53.5165C24.0664 53.0394 24.754 52.45 25.3434 51.7483L27.4904 53.1797C26.3117 55.1724 24.7821 56.744 22.9017 57.8947C21.0213 59.0454 18.6918 59.6208 15.9133 59.6208C14.4819 59.6208 13.233 59.3682 12.1665 58.863C11.1 58.3859 10.2159 57.7123 9.5143 56.8423C8.84072 55.9442 8.33554 54.8917 7.99875 53.6849C7.66196 52.45 7.49356 51.0888 7.49356 49.6013V19.2482H0V17.6484L7.49356 16.083V3.33486L13.5979 0.935238Z"
        fill="#FDE872"
      />
    </svg>
  );
}

/** Brand glyphs aren't in lucide-react, so these two use lucide's original paths. */
export function LinkedinIcon({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={24 / size} strokeLinecap="round" strokeLinejoin="round" className={cx("shrink-0", className)} aria-hidden>
      <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
      <rect width="4" height="12" x="2" y="9" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

export function InstagramIcon({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={24 / size} strokeLinecap="round" strokeLinejoin="round" className={cx("shrink-0", className)} aria-hidden>
      <rect width="20" height="20" x="2" y="2" rx="5" ry="5" />
      <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
      <line x1="17.5" x2="17.51" y1="6.5" y2="6.5" />
    </svg>
  );
}

/**
 * The event dashboard: everyone you've tapped.
 * Figma: "Refined / event (connections) (Dark)" on Page 4.
 *
 * Connections come from GET /events/{id}/connections. They appear once the
 * bracelet data is processed (not built yet), so for now most people will
 * see the empty state. Match % and conversation notes from the Figma card
 * need the AI step, so they aren't shown with made-up values.
 */

import { ChevronRight, Copy, FileText, Globe, Mail, Mic, Play, Watch } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, ApiError, tokenStore, type Connection, type Me } from "../api";
import {
  Button,
  buttonClass,
  Card,
  cx,
  DisplayTitle,
  ErrorNote,
  Icon,
  IconBubble,
  InstagramIcon,
  LinkedinIcon,
  Loading,
  Screen,
  StatusPill,
} from "../components/ui";
import { useEventContext } from "../hooks";
import { braceletStore } from "../session";

type Tab = "connected" | "recommendations";

function Badge({ tone, icon, children }: { tone: "yellow" | "glass"; icon?: ReactNode; children: ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full py-1 pr-2.5 pl-2 text-label-s font-semibold",
        tone === "yellow" ? "bg-yellow text-dark" : "bg-white/30 text-highlight",
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** Glass pill action ("LinkedIn", "Email"...), 40px tall. */
function ReachAt({
  href,
  onClick,
  icon,
  label,
  children,
}: {
  href?: string;
  onClick?: () => void;
  icon: ReactNode;
  label?: string;
  children: ReactNode;
}) {
  const cls = "flex min-h-10 items-center gap-1.5 rounded-full bg-white/20 py-3 pr-3.5 pl-3 text-label-s font-semibold text-highlight";
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>
      {icon}
      {children}
    </a>
  ) : (
    <button type="button" onClick={onClick} aria-label={label} className={cls}>
      {icon}
      {children}
    </button>
  );
}

/** "@handle" or a URL -> a link to the Instagram profile. */
function instagramUrl(value: string) {
  return value.startsWith("http") ? value : `https://instagram.com/${value.replace(/^@/, "")}`;
}

export function ConnectionCard({ person }: { person: Connection }) {
  const [copied, setCopied] = useState(false);
  const c = person.contact;
  const subtitle = person.position ?? ([person.major, person.school].filter(Boolean).join(" · ") || null);
  const photo = api.mediaUrl(person.photo_url);

  const copyEmail = async () => {
    if (!c.email) return;
    try {
      await navigator.clipboard.writeText(c.email);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      window.location.href = `mailto:${c.email}`; // clipboard blocked: open mail instead
    }
  };

  const reach = [
    c.linkedin_url && <ReachAt key="li" href={c.linkedin_url} icon={<LinkedinIcon />}>LinkedIn</ReachAt>,
    c.email && (
      <ReachAt key="em" onClick={copyEmail} label={copied ? "Email copied" : "Copy email"} icon={<Icon icon={Copy} />}>
        {copied ? "Copied" : "Email"}
      </ReachAt>
    ),
    c.portfolio_url && <ReachAt key="pf" href={c.portfolio_url} icon={<Icon icon={Globe} />}>Portfolio</ReachAt>,
    c.website && <ReachAt key="ws" href={c.website} icon={<Icon icon={Globe} />}>Website</ReachAt>,
    c.instagram && <ReachAt key="ig" href={instagramUrl(c.instagram)} icon={<InstagramIcon />}>Instagram</ReachAt>,
  ].filter(Boolean);

  return (
    <Card as="article" className="flex flex-col gap-4 px-5 pt-5 pb-2">
      <div className="flex items-start gap-4">
        {photo ? (
          <img src={photo} alt="" className="size-16 shrink-0 rounded-full object-cover" />
        ) : (
          <span aria-hidden className="size-16 shrink-0 rounded-full bg-highlight" />
        )}
        <div className="flex min-w-0 flex-col gap-1 text-highlight">
          <h3 className="text-label font-medium">{person.name}</h3>
          {subtitle && <p className="text-caption">{subtitle}</p>}
          <div className="flex gap-1.5 pt-1">
            {person.recorded ? (
              <Badge tone="yellow" icon={<Icon icon={Mic} size={12} />}>Recorded</Badge>
            ) : (
              <Badge tone="glass">Contact only</Badge>
            )}
          </div>
        </div>
      </div>
      {person.bio && <p className="text-body text-highlight">{person.bio}</p>}
      {reach.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-label-s font-semibold text-highlight">Reach at</p>
          <div className="flex flex-wrap gap-2">{reach}</div>
        </div>
      )}
      <div className="h-px w-full bg-highlight" />
      <div className="flex items-center gap-3 pt-2 pb-3 text-highlight">
        <Icon icon={FileText} size={20} />
        <div className="flex flex-1 flex-col gap-0.5">
          <p className="text-label font-medium">Conversation notes</p>
          <p className="text-caption">
            {person.recorded ? "AI summary · voice notes · in your email" : "Voice notes · in your email"}
          </p>
        </div>
        <Icon icon={ChevronRight} size={20} />
      </div>
    </Card>
  );
}

export default function EventHome() {
  const { eventId, braceletId, eventName } = useEventContext();
  const [me, setMe] = useState<Me | null>(null);
  const [bracelet, setBracelet] = useState<string | null>(null);
  const [people, setPeople] = useState<Connection[] | null>(null);
  const [tab, setTab] = useState<Tab>("connected");
  const [error, setError] = useState<string | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(!tokenStore.get());

  const load = useCallback(async () => {
    if (!eventId || !tokenStore.get()) return;
    setError(null);
    try {
      const profile = await api.me();
      if (!profile.onboarding.complete) {
        setNeedsOnboarding(true);
        return;
      }
      setMe(profile);
      // This phone tapped a bracelet that isn't linked yet (e.g. a returning
      // attendee at a new event): link it now.
      const assignment = await api.myBracelet(eventId).catch(async (err) => {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
        if (!braceletId) return null;
        return api.claimBracelet(eventId, braceletId).catch((claimErr) => {
          // Held by someone else: show "no bracelet linked" instead of an
          // error that would block the dashboard on every visit.
          if (claimErr instanceof ApiError && claimErr.status === 409) {
            braceletStore.clear(eventId);
            return null;
          }
          throw claimErr;
        });
      });
      setBracelet(assignment?.bracelet_id ?? null);
      setPeople(await api.connections(eventId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setNeedsOnboarding(true);
      else setError(err instanceof ApiError ? err.message : "Couldn't load your connections.");
    }
  }, [eventId, braceletId]);

  useEffect(() => void load(), [load]);

  if (!eventId) return <Navigate to="/" replace />;
  // New people start with how it works; anyone part way through goes back to step 1.
  if (needsOnboarding) return <Navigate to={tokenStore.get() ? `/e/${eventId}/welcome` : `/e/${eventId}/tutorial`} replace />;
  if (error)
    return (
      <Screen className="gap-4 pt-[31px]">
        <div className="relative flex flex-col gap-4">
          <ErrorNote>{error}</ErrorNote>
          <button type="button" onClick={() => void load()} className="min-h-11 self-start text-body font-semibold underline">
            Try again
          </button>
        </div>
      </Screen>
    );
  if (!me || people === null) return <Screen><Loading label="Loading your connections" /></Screen>;

  const wantsRecs = me.preferences.recommendations_opt_in;

  return (
    <Screen className="gap-8 pt-[31px] pb-10">
      <section className="relative flex flex-col gap-4">
        <StatusPill icon={<Icon icon={Watch} />}>
          {bracelet ? `Bracelet ${bracelet}` : "No bracelet linked. Ask staff at check-in."}
        </StatusPill>
        <DisplayTitle>{eventName}.</DisplayTitle>
        <p className="text-body text-highlight">
          You’re using trO to keep your connections with the Trojan family. Everyone you tap shows up here, and you’ll get
          the same list by email with ways to follow up and any notes you took.
        </p>
        <Link to={`/e/${eventId}/tutorial`} className={buttonClass("primary", "self-start")}>
          <Icon icon={Play} />
          Tutorial
        </Link>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="flex items-baseline gap-2 text-title font-semibold text-highlight">
          Your Connections
          <span className="text-yellow tabular-nums">{people.length}</span>
        </h2>

        <div role="tablist" className="flex gap-1 rounded-[13px] bg-highlight p-1">
          {(["connected", "recommendations"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              type="button"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cx(
                "min-h-[37px] flex-1 py-2.5 text-label font-medium transition-colors",
                tab === t ? "rounded-[15px] bg-highlight text-dark shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "rounded-[10px] text-dark/50",
              )}
            >
              {t === "connected" ? "Connected" : "Recommendations"}
            </button>
          ))}
        </div>

        {tab === "connected" ? (
          people.length ? (
            people.map((p) => <ConnectionCard key={p.user_id} person={p} />)
          ) : (
            <Empty title="No connections yet">
              When you meet someone, hold your bracelets together for about a second. They’ll show up here.
            </Empty>
          )
        ) : wantsRecs ? (
          <Empty title="Recommendations are on the way">
            We’ll suggest people to meet based on your profile and include them in your summary email.
          </Empty>
        ) : (
          <Empty title="Recommendations are off">
            You chose not to get recommendations.{" "}
            <Link to={`/e/${eventId}/preferences`} className="font-semibold text-highlight underline">
              Change preferences
            </Link>
          </Empty>
        )}
      </section>

      <TestEmail eventId={eventId} email={me.profile.email} />
    </Screen>
  );
}

/** Bottom of the page: send yourself the summary email now, to try it out. */
export function TestEmail({ eventId, email }: { eventId: number; email: string | null }) {
  const [state, setState] = useState<{ status: "idle" | "sending" | "sent" | "error"; message?: string }>({
    status: "idle",
  });

  const send = async () => {
    setState({ status: "sending" });
    try {
      const { sent_to, delivered } = await api.testEmail(eventId);
      setState({
        status: "sent",
        message: delivered
          ? `Sent to ${sent_to}. Check your inbox.`
          : `Made your email for ${sent_to}, but the server saves emails to a folder instead of sending them. Set up SMTP on the server to get it in your inbox.`,
      });
    } catch (err) {
      setState({ status: "error", message: err instanceof ApiError ? err.message : "Couldn't send the email." });
    }
  };

  return (
    <Card className="flex flex-col gap-3 bg-[rgb(27_24_25/0.6)] p-5">
      <div className="flex items-start gap-3">
        <IconBubble tone="maroon">
          <Icon icon={Mail} size={20} />
        </IconBubble>
        <div className="flex flex-col gap-0.5">
          <p className="text-label font-medium text-highlight">Test your summary email</p>
          <p className="text-caption text-highlight/50">
            {email ? `We’ll send ${email} your summary as it looks right now.` : "Add an email to your profile first."}
          </p>
        </div>
      </div>
      <Button type="button" variant="soft" arrow={false} onClick={() => void send()} disabled={!email || state.status === "sending"}>
        {state.status === "sending" ? "Sending…" : state.status === "sent" ? "Send again" : "Send me a test email"}
      </Button>
      {state.status === "sent" && (
        <p role="status" className="text-caption text-highlight">
          {state.message}
        </p>
      )}
      {state.status === "error" && <ErrorNote>{state.message}</ErrorNote>}
    </Card>
  );
}

function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-[20px] border border-dashed border-highlight/30 bg-highlight/[0.06] p-6 text-center">
      <p className="text-label font-medium text-highlight">{title}</p>
      <p className="text-caption text-highlight/70">{children}</p>
    </div>
  );
}

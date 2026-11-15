/**
 * The event dashboard: everyone you've tapped.
 * Figma: "Refined / event (connections)" (node 29:51).
 *
 * Connections come from GET /events/{id}/connections. They appear once the
 * bracelet data is processed (not built yet), so for now most people will
 * see the empty state. Match % and conversation notes from the Figma card
 * need the AI step, so they aren't shown with made-up values.
 */

import { Copy, FileText, Globe, Mail, Mic, Play, Watch } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, ApiError, tokenStore, type Connection, type Me } from "../api";
import {
  DisplayTitle,
  ErrorNote,
  IconBubble,
  InstagramIcon,
  LinkedinIcon,
  Loading,
  Screen,
  SecondaryButton,
  StatusPill,
} from "../components/ui";
import { useEventContext } from "../hooks";
import { braceletStore } from "../session";

type Tab = "connected" | "recommendations";

function Badge({ dark, icon, children }: { dark?: boolean; icon?: ReactNode; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full py-1 pr-2.5 pl-2 text-caption font-semibold ${
        dark ? "bg-ink text-white" : "bg-soft text-ink"
      }`}
    >
      {icon}
      {children}
    </span>
  );
}

/** Rounded outline action ("LinkedIn", "Copy email"...), 44px tall. */
function ReachAt({ href, onClick, icon, children }: { href?: string; onClick?: () => void; icon: ReactNode; children: ReactNode }) {
  const cls = "flex min-h-11 items-center gap-1.5 rounded-full border border-line py-3 pr-3.5 pl-3 text-caption font-semibold";
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>
      {icon}
      {children}
    </a>
  ) : (
    <button type="button" onClick={onClick} className={cls}>
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
    c.linkedin_url && <ReachAt key="li" href={c.linkedin_url} icon={<LinkedinIcon className="size-4" />}>LinkedIn</ReachAt>,
    c.email && (
      <ReachAt key="em" onClick={copyEmail} icon={<Copy aria-hidden className="size-4" />}>
        {copied ? "Copied" : "Copy email"}
      </ReachAt>
    ),
    c.portfolio_url && <ReachAt key="pf" href={c.portfolio_url} icon={<Globe aria-hidden className="size-4" />}>Portfolio</ReachAt>,
    c.website && <ReachAt key="ws" href={c.website} icon={<Globe aria-hidden className="size-4" />}>Website</ReachAt>,
    c.instagram && <ReachAt key="ig" href={instagramUrl(c.instagram)} icon={<InstagramIcon className="size-4" />}>Instagram</ReachAt>,
  ].filter(Boolean);

  return (
    <article className="flex flex-col gap-4 rounded-[20px] border border-line px-5 pt-5 pb-2">
      <div className="flex items-start gap-4">
        {photo ? (
          <img src={photo} alt="" className="size-16 shrink-0 rounded-full object-cover" />
        ) : (
          <span aria-hidden className="size-16 shrink-0 rounded-full bg-soft" />
        )}
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="text-body font-semibold">{person.name}</h3>
          {subtitle && <p className="text-caption text-ink-muted italic">{subtitle}</p>}
          <div className="flex gap-1.5 pt-1">
            {person.recorded ? (
              <Badge dark icon={<Mic aria-hidden className="size-3" />}>Recorded</Badge>
            ) : (
              <Badge>Contact only</Badge>
            )}
          </div>
        </div>
      </div>
      {person.bio && <p className="text-body text-ink-body">{person.bio}</p>}
      {reach.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-caption font-semibold text-ink-muted">Reach at</p>
          <div className="flex flex-wrap gap-2">{reach}</div>
        </div>
      )}
      <div className="h-px w-full bg-line" />
      <div className="flex items-center gap-3 pt-2 pb-3">
        <FileText aria-hidden className="size-5 shrink-0" />
        <div className="flex flex-col gap-0.5">
          <p className="text-body font-semibold">Conversation notes</p>
          <p className="text-caption text-ink-muted">
            {person.recorded ? "AI summary and your voice notes" : "Your voice notes"} arrive in your summary email.
          </p>
        </div>
      </div>
    </article>
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
  if (needsOnboarding) return <Navigate to={`/e/${eventId}/welcome`} replace />;
  if (error)
    return (
      <Screen className="gap-4">
        <ErrorNote>{error}</ErrorNote>
        <button type="button" onClick={() => void load()} className="min-h-11 self-start text-body font-semibold underline">
          Try again
        </button>
      </Screen>
    );
  if (!me || people === null) return <Screen><Loading label="Loading your connections" /></Screen>;

  const wantsRecs = me.preferences.recommendations_opt_in;

  return (
    <Screen className="gap-8 pb-10">
      <section className="flex flex-col gap-4">
        <StatusPill icon={<Watch />}>
          {bracelet ? `Bracelet ${bracelet} · Summary by email` : "No bracelet linked. Ask staff at check-in."}
        </StatusPill>
        <DisplayTitle>{eventName}</DisplayTitle>
        <p className="text-body text-ink-body">
          You’re using trO to keep your connections with the Trojan family. Everyone you tap shows up here, and you’ll get
          the same list by email with ways to follow up and any notes you took.
        </p>
        <Link
          to={`/e/${eventId}/tutorial`}
          className="flex min-h-11 items-center gap-2 self-start rounded-full border border-line py-3 pr-4 pl-3.5 text-body font-semibold"
        >
          <Play aria-hidden className="size-3.5" />
          Tutorial
        </Link>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="flex items-baseline gap-2 text-title font-semibold">
          Your Connections
          <span className="font-mono font-medium text-ink-muted tabular-nums">{people.length}</span>
        </h2>

        <div role="tablist" className="flex gap-1 rounded-[14px] bg-soft p-1">
          {(["connected", "recommendations"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              type="button"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`min-h-[41px] flex-1 rounded-[10px] text-body font-semibold transition-colors ${
                tab === t ? "bg-bg text-ink shadow-[0_1px_3px_rgba(0,0,0,0.08)]" : "text-ink-muted"
              }`}
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
            <Link to={`/e/${eventId}/preferences`} className="font-semibold text-ink underline">
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
    <section className="flex flex-col gap-3 rounded-[20px] border border-line p-5">
      <div className="flex items-start gap-3">
        <IconBubble>
          <Mail />
        </IconBubble>
        <div className="flex flex-col gap-0.5">
          <p className="text-body font-semibold text-ink">Test your summary email</p>
          <p className="text-caption text-ink-muted">
            {email ? `We’ll send ${email} your summary as it looks right now.` : "Add an email to your profile first."}
          </p>
        </div>
      </div>
      <div className="flex">
        <SecondaryButton type="button" onClick={() => void send()} disabled={!email || state.status === "sending"}>
          {state.status === "sending" ? "Sending…" : state.status === "sent" ? "Send again" : "Send me a test email"}
        </SecondaryButton>
      </div>
      {state.status === "sent" && (
        <p role="status" className="text-caption text-ink-body">
          {state.message}
        </p>
      )}
      {state.status === "error" && <ErrorNote>{state.message}</ErrorNote>}
    </section>
  );
}

function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-[20px] border border-dashed border-line p-6 text-center">
      <p className="text-body font-semibold">{title}</p>
      <p className="text-caption text-ink-muted">{children}</p>
    </div>
  );
}

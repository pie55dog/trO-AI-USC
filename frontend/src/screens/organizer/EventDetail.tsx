import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import type { EventInfo } from "../../api";
import { ErrorNote, Loading } from "../../components/ui";
import { formatWhen, organizerApi, type Attendee, type Overview } from "../../organizerApi";
import AfterEvent from "./AfterEvent";
import Attendees from "./Attendees";
import EventForm from "./EventForm";
import { cx } from "./Organizer";
import Registration from "./Registration";

const TABS = [
  { id: "registration", label: "Registration" },
  { id: "attendees", label: "Attendees" },
  { id: "after", label: "After the event" },
  { id: "details", label: "Details" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/** How often the counts and roster refresh while the page is open during an event. */
const REFRESH_MS = 15_000;

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/** The state of the event in a sentence or two, instead of a wall of numbers. */
function summary(o: Overview): string {
  if (o.attendees === 0) return "No one has checked in yet.";
  const parts = [
    `${plural(o.attendees, "person", "people")} checked in.`,
    `${o.recording_consent} agreed to recording.`,
    o.connections ? `${plural(o.connections, "tap")} so far.` : "No taps yet.",
  ];
  if (o.emails_sent) parts.push(`${plural(o.emails_sent, "summary email")} sent.`);
  return parts.join(" ");
}

export default function EventDetail({ onEventChanged }: { onEventChanged: (e: EventInfo) => void }) {
  const eventId = Number(useParams().eventId);
  const [params, setParams] = useSearchParams();
  const tab: TabId = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "registration") as TabId;

  const [overview, setOverview] = useState<Overview | null>(null);
  const [attendees, setAttendees] = useState<Attendee[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [o, a] = await Promise.all([organizerApi.overview(eventId), organizerApi.attendees(eventId)]);
      setOverview(o);
      setAttendees(a);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [eventId]);

  useEffect(() => {
    setOverview(null);
    setAttendees(null);
    refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  if (!overview) return error ? <ErrorNote>{error}</ErrorNote> : <Loading label="Loading event" />;
  const event = overview.event;
  const when = formatWhen(event.starts_at);

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <h1 className="text-display font-normal italic break-words">{event.name}</h1>
        {(when || event.location) && (
          <p className="text-body text-ink-muted">
            {[when, event.location].filter(Boolean).join(", ")}
          </p>
        )}
        <p aria-live="polite" className="max-w-[60ch] text-title text-pretty text-ink">
          {summary(overview)}
        </p>
      </header>

      {error && <ErrorNote>{error}</ErrorNote>}

      <nav aria-label="Event sections" className="-mx-6 overflow-x-auto px-6 lg:mx-0 lg:px-0">
        <div className="flex gap-1 border-b border-line">
          {TABS.map((t) => (
            <Link
              key={t.id}
              to={{ search: t.id === "registration" ? "" : `?tab=${t.id}` }}
              aria-current={tab === t.id ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                setParams(t.id === "registration" ? {} : { tab: t.id }, { replace: true });
              }}
              className={cx(
                "-mb-px flex min-h-11 items-center gap-1.5 border-b-2 px-3 text-body whitespace-nowrap",
                tab === t.id ? "border-ink font-semibold text-ink" : "border-transparent text-ink-muted hover:text-ink",
              )}
            >
              {t.label}
              {t.id === "attendees" && (
                <span className="rounded-full bg-soft px-2 text-caption font-semibold text-ink">{overview.attendees}</span>
              )}
            </Link>
          ))}
        </div>
      </nav>

      {tab === "registration" && <Registration eventId={eventId} onChanged={refresh} />}
      {tab === "attendees" && <Attendees eventId={eventId} attendees={attendees} onChanged={refresh} />}
      {tab === "after" && <AfterEvent eventId={eventId} overview={overview} onChanged={refresh} />}
      {tab === "details" && (
        <section className="flex flex-col gap-4">
          <p className="max-w-[60ch] text-body text-ink-muted">
            Changes show up on attendees' phones the next time they open the event, and in the summary email.
          </p>
          <EventForm
            key={event.id}
            initial={event}
            submitLabel="Save changes"
            doneLabel="Saved"
            onSubmit={async (fields) => {
              const saved = await organizerApi.updateEvent(eventId, fields);
              setOverview((o) => (o ? { ...o, event: saved } : o));
              onEventChanged(saved);
            }}
          />
        </section>
      )}
    </article>
  );
}

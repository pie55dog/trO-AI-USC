import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import type { EventInfo } from "../../api";
import { cx, ErrorNote } from "../../components/ui";
import { formatWhen, organizerApi, type Attendee, type Overview } from "../../organizerApi";
import AfterEvent from "./AfterEvent";
import Attendees from "./Attendees";
import EventForm from "./EventForm";
import { displayClass, InlineLoading } from "./parts";
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

  if (!overview) return error ? <ErrorNote>{error}</ErrorNote> : <InlineLoading label="Loading event" />;
  const event = overview.event;
  const when = formatWhen(event.starts_at);

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <h1 className={cx(displayClass, "break-words")}>{event.name}</h1>
        {(when || event.location) && (
          <p className="text-body text-highlight/60">
            {[when, event.location].filter(Boolean).join(", ")}
          </p>
        )}
        <p aria-live="polite" className="max-w-[60ch] pt-2 text-title text-pretty text-highlight">
          {summary(overview)}
        </p>
      </header>

      {error && <ErrorNote>{error}</ErrorNote>}

      <nav aria-label="Event sections" className="-mx-[25px] overflow-x-auto px-[25px] lg:mx-0 lg:px-0">
        <div className="flex w-max gap-1 rounded-[13px] bg-highlight/[0.06] p-1">
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
                "flex min-h-10 items-center gap-1.5 px-4 text-label whitespace-nowrap text-highlight",
                tab === t.id
                  ? "rounded-[15px] bg-highlight/[0.14] font-medium shadow-[0_1px_3px_rgba(0,0,0,0.08)]"
                  : "rounded-[10px] text-highlight/70 hover:text-highlight",
              )}
            >
              {t.label}
              {t.id === "attendees" && (
                <span className="text-yellow tabular-nums">{overview.attendees}</span>
              )}
            </Link>
          ))}
        </div>
      </nav>

      {tab === "registration" && <Registration eventId={eventId} onChanged={refresh} />}
      {tab === "attendees" && <Attendees eventId={eventId} attendees={attendees} onChanged={refresh} />}
      {tab === "after" && <AfterEvent eventId={eventId} overview={overview} onChanged={refresh} />}
      {tab === "details" && (
        <section className="glass flex flex-col gap-5 rounded-[20px] bg-highlight/[0.03] p-5 sm:p-6">
          <p className="max-w-[60ch] text-body text-highlight/60">
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

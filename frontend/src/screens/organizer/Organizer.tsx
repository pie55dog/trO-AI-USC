/**
 * Organizer console (/organizer): what event planners use to set up an
 * event, register attendees and send the post-event emails.
 *
 *   /organizer                   sign in with the organizer key, pick an event
 *   /organizer/new               create an event
 *   /organizer/events/:eventId   one event: registration, attendees, emails, details
 *
 * Wider than the attendee screens: a list of events on the left, the chosen
 * event on the right. On a phone the list and the event are separate pages.
 */

import { CalendarPlus, ChevronLeft, LogOut } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes, useMatch, useNavigate } from "react-router-dom";
import { PREVIEW, type EventInfo } from "../../api";
import { ErrorNote, Field, Loading, PrimaryButton } from "../../components/ui";
import { formatWhen, organizerApi } from "../../organizerApi";
import EventDetail from "./EventDetail";
import EventForm from "./EventForm";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await organizerApi.signIn(key);
      onSignedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[440px] flex-col justify-center gap-8 px-6 py-12">
      <header className="flex flex-col gap-2">
        <h1 className="text-display font-normal italic">Run your event with trO.</h1>
        <p className="text-body text-ink-muted">
          Set up the event, get people registered and linked to their bracelets, then send everyone the
          people they met.
        </p>
      </header>
      {PREVIEW ? (
        <ErrorNote>
          This copy of the app isn't connected to a trO server, so there are no events to manage. Open the
          organizer console on a build with VITE_API_URL set.
        </ErrorNote>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field
            label="Organizer key"
            type="password"
            autoComplete="current-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            hint="The ADMIN_API_KEY from the trO server. Whoever set up the server can share it with you."
            error={error}
            required
          />
          <PrimaryButton type="submit" loading={busy} disabled={!key.trim()}>
            Sign in
          </PrimaryButton>
        </form>
      )}
    </main>
  );
}

function EventList({ events, onSignOut }: { events: EventInfo[] | null; onSignOut: () => void }) {
  return (
    <div className="flex h-full flex-col gap-6">
      <div className="flex items-baseline justify-between">
        <Link to="/organizer" className="text-title font-semibold italic">
          trO organizer
        </Link>
      </div>
      <Link
        to="/organizer/new"
        className="flex min-h-11 items-center justify-center gap-2 rounded-[14px] bg-ink px-4 py-3 text-body font-semibold text-white"
      >
        <CalendarPlus aria-hidden className="size-4" />
        New event
      </Link>
      <nav aria-label="Your events" className="flex flex-col gap-1">
        <h2 className="px-3 pb-1 text-caption font-semibold text-ink-muted">Your events</h2>
        {events === null ? (
          <Loading label="Loading events" />
        ) : events.length === 0 ? (
          <p className="px-3 text-caption text-ink-muted">No events yet.</p>
        ) : (
          events.map((ev) => (
            <NavLink
              key={ev.id}
              to={`/organizer/events/${ev.id}`}
              className={({ isActive }) =>
                cx(
                  "flex flex-col gap-0.5 rounded-xl px-3 py-2.5",
                  isActive ? "bg-ink text-white" : "text-ink hover:bg-soft",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span className="text-body font-semibold">{ev.name}</span>
                  <span className={cx("text-caption", isActive ? "text-white/70" : "text-ink-muted")}>
                    {formatWhen(ev.starts_at) ?? "No date yet"}
                  </span>
                </>
              )}
            </NavLink>
          ))
        )}
      </nav>
      <button
        type="button"
        onClick={onSignOut}
        className="mt-auto flex min-h-11 items-center gap-2 self-start rounded-xl px-3 text-caption font-semibold text-ink-muted hover:bg-soft"
      >
        <LogOut aria-hidden className="size-4" />
        Sign out
      </button>
    </div>
  );
}

function NewEvent({ onCreated }: { onCreated: (e: EventInfo) => void }) {
  return (
    <section className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-display font-normal italic">New event</h1>
        <p className="text-body text-ink-muted">
          Attendees see this name on their phone and in the summary email the morning after.
        </p>
      </header>
      <EventForm
        submitLabel="Create event"
        onSubmit={async (fields) => onCreated(await organizerApi.createEvent(fields))}
      />
    </section>
  );
}

function Start({ events }: { events: EventInfo[] | null }) {
  return (
    <section className="flex flex-col gap-3">
      <h1 className="text-display font-normal italic">
        {events && events.length === 0 ? "Set up your first event." : "Pick an event."}
      </h1>
      <p className="max-w-[60ch] text-body text-ink-muted">
        {events && events.length === 0
          ? "Create the event, then share its link so attendees can set up their profiles before they pick up a bracelet."
          : "Choose an event from the list to see who's registered, link bracelets at the door, or send the summary emails."}
      </p>
      {events && events.length === 0 && (
        <Link to="/organizer/new" className="mt-3 self-start rounded-[14px] bg-ink px-5 py-3.5 text-body font-semibold text-white">
          Create an event
        </Link>
      )}
    </section>
  );
}

export default function Organizer() {
  const navigate = useNavigate();
  const [signedIn, setSignedIn] = useState(organizerApi.signedIn());
  const [events, setEvents] = useState<EventInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // On a phone the list is its own page; the event pages show a back link instead.
  const atRoot = useMatch("/organizer");

  const loadEvents = useCallback(() => {
    organizerApi.events().then(
      (list) => {
        setEvents(list);
        setError(null);
      },
      (err) => setError(err instanceof Error ? err.message : String(err)),
    );
  }, []);

  useEffect(() => {
    if (!signedIn) return;
    // A key changed on the server since last visit lands back on sign-in.
    organizerApi.check().catch(() => setSignedIn(organizerApi.signedIn()));
    loadEvents();
  }, [signedIn, loadEvents]);

  if (!signedIn) return <SignIn onSignedIn={() => setSignedIn(true)} />;

  const signOut = () => {
    organizerApi.signOut();
    setSignedIn(false);
    navigate("/organizer");
  };

  const updateEvent = (ev: EventInfo) =>
    setEvents((list) => (list ? list.map((e) => (e.id === ev.id ? ev : e)) : list));

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[280px_1fr]">
      <aside
        className={cx(
          "border-line px-4 py-6 lg:sticky lg:top-0 lg:block lg:h-dvh lg:overflow-y-auto lg:border-r",
          atRoot ? "block" : "hidden",
        )}
      >
        <EventList events={events} onSignOut={signOut} />
      </aside>
      <main className={cx("min-w-0 px-6 pt-6 pb-16 lg:px-12 lg:pt-12", atRoot && "hidden lg:block")}>
        <div className="mx-auto flex max-w-[880px] flex-col gap-6">
          {!atRoot && (
            <Link to="/organizer" className="-ml-1 flex items-center gap-1 self-start text-caption font-semibold text-ink-muted lg:hidden">
              <ChevronLeft aria-hidden className="size-4" />
              All events
            </Link>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
          <Routes>
            <Route index element={<Start events={events} />} />
            <Route
              path="new"
              element={
                <NewEvent
                  onCreated={(ev) => {
                    setEvents((list) => [ev, ...(list ?? [])]);
                    navigate(`/organizer/events/${ev.id}`);
                  }}
                />
              }
            />
            <Route path="events/:eventId" element={<EventDetail onEventChanged={updateEvent} />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

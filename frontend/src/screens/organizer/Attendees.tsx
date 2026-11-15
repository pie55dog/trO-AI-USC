import { Download, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../../api";
import { ErrorNote, Loading } from "../../components/ui";
import { organizerApi, type Attendee } from "../../organizerApi";
import { cx } from "./Organizer";

function emailLabel(a: Attendee): string {
  if (a.email_status === "sent") return "Sent";
  if (a.email_status === "failed") return "Failed";
  if (!a.summary_email_opt_in) return "Opted out";
  return "Not sent yet";
}

function toCsv(rows: Attendee[]): string {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const head = ["Name", "Email", "School", "Major", "Bracelet", "Checked in", "Recording", "Taps", "Summary email"];
  const body = rows.map((a) =>
    [a.name, a.email, a.school, a.major, a.bracelet_id, a.assigned_at, a.recording_consent ? "Yes" : "No", a.connections, emailLabel(a)]
      .map(esc)
      .join(","),
  );
  return [head.join(","), ...body].join("\n");
}

/** Two-step "Take back" so a misclick never frees someone's bracelet. */
function TakeBack({ eventId, person, onDone }: { eventId: number; person: Attendee; onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!confirming)
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="min-h-9 rounded-full border border-line px-3 text-caption font-semibold hover:bg-soft"
      >
        Take back
      </button>
    );

  const release = async () => {
    setBusy(true);
    try {
      await organizerApi.release(eventId, person.user_id);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <span className="flex flex-wrap items-center justify-end gap-2">
      {error && <span className="text-caption text-danger">{error}</span>}
      <button type="button" onClick={() => setConfirming(false)} className="min-h-9 px-2 text-caption text-ink-muted">
        Keep
      </button>
      <button
        type="button"
        onClick={release}
        disabled={busy}
        aria-label={`Take back ${person.name}'s bracelet`}
        className="min-h-9 rounded-full bg-danger px-3 text-caption font-semibold text-white disabled:opacity-40"
      >
        Take back {person.bracelet_id}
      </button>
    </span>
  );
}

export default function Attendees({
  eventId,
  attendees,
  onChanged,
}: {
  eventId: number;
  attendees: Attendee[] | null;
  onChanged: () => void;
}) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!attendees || !q) return attendees ?? [];
    return attendees.filter((a) =>
      [a.name, a.email, a.bracelet_id, a.school, a.major].some((v) => v?.toLowerCase().includes(q)),
    );
  }, [attendees, query]);

  if (attendees === null) return <Loading label="Loading attendees" />;
  if (attendees.length === 0)
    return (
      <p className="max-w-[60ch] text-body text-ink-muted">
        No one has checked in yet. People show up here as soon as their bracelet is linked, either by tapping it to
        their phone or at the check-in desk on the Registration tab.
      </p>
    );

  const csvHref = `data:text/csv;charset=utf-8,${encodeURIComponent(toCsv(attendees))}`;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative flex min-w-0 flex-1 items-center sm:max-w-[360px]">
          <span className="sr-only">Search attendees</span>
          <Search aria-hidden className="pointer-events-none absolute left-4 size-4 text-ink-muted" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name, email or bracelet"
            className="w-full rounded-xl border border-line bg-bg py-[11px] pr-4 pl-10 text-body placeholder:text-ink-muted"
          />
        </label>
        <a
          href={csvHref}
          download={`tro-event-${eventId}-attendees.csv`}
          className="flex min-h-11 items-center gap-1.5 rounded-full border border-line px-4 text-caption font-semibold hover:bg-soft"
        >
          <Download aria-hidden className="size-4" />
          Export CSV
        </a>
      </div>

      {shown.length === 0 ? (
        <ErrorNote>No attendee matches "{query}". Try part of their name, email or bracelet ID.</ErrorNote>
      ) : (
        <div className="-mx-6 overflow-x-auto px-6 lg:mx-0 lg:px-0">
          <table className="w-full min-w-[720px] text-left text-body">
            <thead>
              <tr className="border-b border-line text-caption text-ink-muted">
                <th scope="col" className="py-2 pr-4 font-semibold">Attendee</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Bracelet</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Recording</th>
                <th scope="col" className="py-2 pr-4 text-right font-semibold">Taps</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Summary email</th>
                <th scope="col" className="py-2 font-semibold"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => {
                const photo = api.mediaUrl(a.photo_url);
                return (
                  <tr key={a.user_id} className="border-b border-line align-middle">
                    <td className="py-3 pr-4">
                      <span className="flex items-center gap-3">
                        {photo ? (
                          <img src={photo} alt="" className="size-9 shrink-0 rounded-full object-cover" />
                        ) : (
                          <span aria-hidden className="size-9 shrink-0 rounded-full bg-soft" />
                        )}
                        <span className="flex min-w-0 flex-col">
                          <span className="font-semibold">{a.name}</span>
                          <span className="truncate text-caption text-ink-muted">{a.email}</span>
                        </span>
                      </span>
                    </td>
                    <td className="py-3 pr-4 font-mono text-caption">{a.bracelet_id}</td>
                    <td className="py-3 pr-4">{a.recording_consent ? "Yes" : "No"}</td>
                    <td className="py-3 pr-4 text-right tabular-nums">{a.connections}</td>
                    <td className={cx("py-3 pr-4", a.email_status === "failed" ? "text-danger" : a.email_status === "sent" ? "text-ink" : "text-ink-muted")}>
                      {emailLabel(a)}
                    </td>
                    <td className="py-3 text-right">
                      <TakeBack eventId={eventId} person={a} onDone={onChanged} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

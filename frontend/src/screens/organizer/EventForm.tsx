import { useState, type FormEvent } from "react";
import type { EventInfo } from "../../api";
import { Button, ErrorNote, Field } from "../../components/ui";
import { toLocalInput, type EventFields } from "../../organizerApi";

/** Name, place and start time. Used to create an event and to edit one. */
export default function EventForm({
  initial,
  submitLabel,
  doneLabel,
  onSubmit,
}: {
  initial?: EventInfo;
  submitLabel: string;
  /** Shown after a successful save when the form stays on screen. */
  doneLabel?: string;
  onSubmit: (fields: EventFields) => Promise<void>;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [startsAt, setStartsAt] = useState(toLocalInput(initial?.starts_at ?? null));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await onSubmit({
        name: name.trim(),
        location: location.trim() || null,
        // The input is local time; the server stores UTC.
        starts_at: startsAt ? new Date(startsAt).toISOString() : null,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex max-w-[520px] flex-col gap-5" onChange={() => setDone(false)}>
      <Field
        label="Event name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Viterbi Industry Night"
        maxLength={120}
        required
      />
      <Field
        label="Where"
        value={location}
        onChange={(e) => setLocation(e.target.value)}
        placeholder="Town & Gown, USC"
        maxLength={120}
        hint="Optional."
      />
      <Field
        label="Starts"
        type="datetime-local"
        value={startsAt}
        onChange={(e) => setStartsAt(e.target.value)}
        hint="Optional. Your local time."
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex items-center gap-4">
        <Button type="submit" loading={busy} disabled={!name.trim()} arrow={false} className="px-8">
          {submitLabel}
        </Button>
        {done && doneLabel && (
          <p role="status" className="text-caption text-yellow">
            {doneLabel}
          </p>
        )}
      </div>
    </form>
  );
}

import { Check, Copy, Download, ExternalLink } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { ErrorNote, Field, PrimaryButton } from "../../components/ui";
import { eventLink, organizerApi } from "../../organizerApi";

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      window.prompt("Copy this:", text); // clipboard blocked (http, old browser)
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-line px-4 text-caption font-semibold hover:bg-soft"
    >
      {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
      {copied ? "Copied" : label}
    </button>
  );
}

function Section({ title, intro, children }: { title: string; intro: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border-t border-line pt-6 first:border-t-0 first:pt-0">
      <div className="flex flex-col gap-1">
        <h2 className="text-title font-semibold">{title}</h2>
        <p className="max-w-[64ch] text-body text-ink-muted">{intro}</p>
      </div>
      {children}
    </section>
  );
}

function AttendeeLink({ eventId }: { eventId: number }) {
  const link = eventLink(eventId);
  const [qr, setQr] = useState<string | null>(null);
  useEffect(() => {
    QRCode.toDataURL(link, { margin: 1, width: 640, color: { dark: "#111111", light: "#ffffff" } }).then(setQr, () => setQr(null));
  }, [link]);

  return (
    <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
      {qr && (
        <img src={qr} alt={`QR code for ${link}`} className="size-40 shrink-0 rounded-[20px] border border-line p-2" />
      )}
      <div className="flex min-w-0 flex-col gap-3">
        <p className="rounded-xl bg-soft px-4 py-3 font-mono text-caption break-all text-ink">{link}</p>
        <div className="flex flex-wrap gap-2">
          <CopyButton text={link} label="Copy link" />
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-h-11 items-center gap-1.5 rounded-full border border-line px-4 text-caption font-semibold hover:bg-soft"
          >
            <ExternalLink aria-hidden className="size-4" />
            Open
          </a>
          {qr && (
            <a
              href={qr}
              download={`tro-event-${eventId}-qr.png`}
              className="flex min-h-11 items-center gap-1.5 rounded-full border border-line px-4 text-caption font-semibold hover:bg-soft"
            >
              <Download aria-hidden className="size-4" />
              Download QR code
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function BraceletLinks({ eventId }: { eventId: number }) {
  const [raw, setRaw] = useState("");
  const rows = useMemo(() => {
    const ids = raw
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    return [...new Set(ids)].map((id) => ({
      id,
      valid: /^[A-Za-z0-9_:\s-]{1,64}$/.test(id),
      link: eventLink(eventId, id),
    }));
  }, [raw, eventId]);
  const good = rows.filter((r) => r.valid);

  return (
    <div className="flex flex-col gap-4">
      <Field
        label="Bracelet IDs"
        multiline
        rows={4}
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder={"A4:CF:12:9B:00:1E\nA4:CF:12:9B:00:2F"}
        hint="One per line. The ESP32 id printed on the bracelet or shown by the firmware."
        className="max-w-[520px]"
      />
      {rows.length > 0 && (
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col divide-y divide-line rounded-[20px] border border-line">
            {rows.map((r) => (
              <li key={r.id} className="flex items-center gap-3 px-4 py-2">
                <span className="w-36 shrink-0 font-mono text-caption">{r.id}</span>
                {r.valid ? (
                  <>
                    <span className="min-w-0 flex-1 truncate font-mono text-caption text-ink-muted">{r.link}</span>
                    <CopyButton text={r.link} />
                  </>
                ) : (
                  <span className="text-caption text-danger">Use only letters, digits, colons or dashes.</span>
                )}
              </li>
            ))}
          </ul>
          {good.length > 1 && (
            <div className="self-start">
              <CopyButton text={good.map((r) => `${r.id},${r.link}`).join("\n")} label={`Copy all ${good.length} as CSV`} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CheckInDesk({ eventId, onChanged }: { eventId: number; onChanged: () => void }) {
  const [email, setEmail] = useState("");
  const [bracelet, setBracelet] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const person = await organizerApi.assign(eventId, email.trim(), bracelet.trim());
      setDone(`Linked bracelet ${person.bracelet_id} to ${person.name}.`);
      setEmail("");
      setBracelet("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex max-w-[640px] flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Attendee email"
          type="email"
          autoComplete="off"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="ttrojan@usc.edu"
          required
        />
        <Field
          label="Bracelet ID"
          autoComplete="off"
          value={bracelet}
          onChange={(e) => setBracelet(e.target.value)}
          placeholder="A4:CF:12:9B:00:1E"
          required
        />
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex flex-wrap items-center gap-4">
        <PrimaryButton type="submit" loading={busy} disabled={!email.trim() || !bracelet.trim()} arrow={false} className="w-auto! px-8">
          Link bracelet
        </PrimaryButton>
        {done && (
          <p role="status" className="text-body text-ink">
            {done}
          </p>
        )}
      </div>
    </form>
  );
}

export default function Registration({ eventId, onChanged }: { eventId: number; onChanged: () => void }) {
  return (
    <div className="flex flex-col gap-10">
      <Section
        title="Attendee link"
        intro="Send this with the invite or put the QR code on a sign. People set up their profile and recording choice here, so check-in takes seconds."
      >
        <AttendeeLink eventId={eventId} />
      </Section>
      <Section
        title="Bracelet tap links"
        intro="Write each bracelet's link to its NFC tag. Tapping the bracelet to a phone opens the event and links that bracelet to whoever is holding the phone."
      >
        <BraceletLinks eventId={eventId} />
      </Section>
      <Section
        title="Check-in desk"
        intro="For anyone whose phone didn't link their bracelet. They need a finished trO profile; look them up by the email they signed up with."
      >
        <CheckInDesk eventId={eventId} onChanged={onChanged} />
      </Section>
    </div>
  );
}

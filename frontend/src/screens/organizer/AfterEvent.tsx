import { useState, type FormEvent } from "react";
import { Button, ErrorNote, Field } from "../../components/ui";
import { organizerApi, type Overview, type SendResult } from "../../organizerApi";
import { Panel } from "./parts";

function resultLine(r: SendResult): string {
  const parts = [`Sent ${r.sent}.`];
  if (r.skipped_already_sent) parts.push(`${r.skipped_already_sent} already had theirs.`);
  if (r.skipped_opted_out) parts.push(`${r.skipped_opted_out} opted out.`);
  if (r.skipped_no_email) parts.push(`${r.skipped_no_email} had no email address.`);
  if (r.failed) parts.push(`${r.failed} failed.`);
  return parts.join(" ");
}

function SendSummaries({ eventId, overview, onChanged }: { eventId: number; overview: Overview; onChanged: () => void }) {
  const [resend, setResend] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SendResult | null>(null);

  // People who'd get an email on this run (the server makes the final call).
  const waiting = Math.max(0, overview.summary_email_opt_in - (resend ? 0 : overview.emails_sent));

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await organizerApi.sendSummaries(eventId, resend));
      setConfirming(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="Summary emails"
      intro="Each attendee gets one email listing everyone they tapped, with only the contact details each person chose to share. Running it again only emails people who haven't had theirs, so it's safe to send more than once."
    >

      <label className="flex items-center gap-3 text-body">
        <input
          type="checkbox"
          checked={resend}
          onChange={(e) => {
            setResend(e.target.checked);
            setConfirming(false);
          }}
          className="size-5 accent-yellow"
        />
        Also resend to people who already got one
      </label>

      {error && <ErrorNote>{error}</ErrorNote>}

      {overview.attendees === 0 ? (
        <p className="text-body text-highlight/60">No one has checked in, so there's no one to email yet.</p>
      ) : confirming ? (
        <div className="flex max-w-[520px] flex-col gap-4 rounded-[20px] border border-yellow/60 bg-yellow/[0.06] p-5">
          <p className="text-body">
            Send summary emails to {waiting === 1 ? "1 attendee" : `up to ${waiting} attendees`} now? This can't be undone.
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="soft" arrow={false} onClick={() => setConfirming(false)} className="flex-1">
              Not yet
            </Button>
            <Button type="button" onClick={send} loading={busy} arrow={false} className="flex-1">
              Send emails
            </Button>
          </div>
        </div>
      ) : (
        <Button
          type="button"
          onClick={() => setConfirming(true)}
          disabled={waiting === 0}
          arrow={false}
          className="self-start px-8"
        >
          {waiting === 0 ? "Everyone has their email" : "Send summary emails"}
        </Button>
      )}

      {result && (
        <div role="status" className="flex flex-col gap-2 rounded-xl bg-highlight/[0.06] p-4">
          <p className="text-label font-medium text-yellow">{resultLine(result)}</p>
          {result.failures.length > 0 && (
            <>
              <p className="text-caption text-highlight/60">Fix these and send again; only the failed ones are retried.</p>
              <ul className="list-disc pl-5 font-mono text-caption text-danger">
                {result.failures.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

function TestEmail() {
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const r = await organizerApi.testEmail(to.trim());
      setDone(
        r.backend === "smtp"
          ? `Sent a test email to ${to.trim()}. Check that inbox.`
          : "The server saved the test email to its outbox folder instead of sending it. Set up email on the server first.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Check email works" intro="Send yourself a short test before the event, so the summaries don't fail the morning after.">
      <form onSubmit={submit} className="flex max-w-[520px] flex-col gap-4">
        <Field label="Send a test to" type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="you@usc.edu" required />
        {error && <ErrorNote>{error}</ErrorNote>}
        {done && (
          <p role="status" className="text-body">
            {done}
          </p>
        )}
        <Button type="submit" variant="soft" loading={busy} arrow={false} disabled={!to.trim()} className="self-start px-8">
          Send test email
        </Button>
      </form>
    </Panel>
  );
}

export default function AfterEvent({ eventId, overview, onChanged }: { eventId: number; overview: Overview; onChanged: () => void }) {
  return (
    <div className="flex flex-col gap-4">
      <SendSummaries eventId={eventId} overview={overview} onChanged={onChanged} />
      <TestEmail />
    </div>
  );
}

/**
 * Conversation notes for one person you met (/e/:eventId/notes/:userId).
 * Opened from the "Conversation notes" row on a connection card (Figma
 * "Refined / event (connections) (Dark)").
 *
 * The Figma file has no frame for this screen yet, so it is built only from
 * pieces already in the file: the yellow display title, glass cards, the
 * badges and pills from the connection card, the back button from the
 * tutorial, and the privacy line from the tutorial. No new colors or sizes.
 *
 * `NotesView` also renders the labelled sample on /demo/notes.
 */

import { ArrowRight, ChevronLeft, ChevronRight, Mic, Quote, Star } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { api, ApiError, type ConversationStatus, type PersonNotes, type TranscriptLine, type VoiceNote } from "../api";
import { Card, cx, DisplayTitle, ErrorNote, Icon, IconBubble, Loading, Screen, StatusPill } from "../components/ui";
import { useEventContext } from "../hooks";
import { Badge, Empty } from "./EventHome";

// While notes are being made, check again this often.
const REFRESH_MS = 5000;

const firstName = (name: string) => name.trim().split(/\s+/)[0] || name;

function time(iso: string) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function BackButton({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      aria-label={label}
      className="glass flex size-10 shrink-0 items-center justify-center rounded-[20px] bg-highlight/[0.08] text-highlight"
    >
      <Icon icon={ChevronLeft} size={20} />
    </Link>
  );
}

/** A glass card with a small heading, like "Reach at" on the connection card. */
function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <Card className={cx("flex flex-col gap-3 p-5", className)}>
      <h2 className="text-label font-medium text-highlight">{title}</h2>
      {children}
    </Card>
  );
}

const SPEAKER_METHOD: Record<string, string> = {
  two_bracelets: "Who said what was measured from both bracelets: each person is louder on their own.",
  one_bracelet: "Who said what was measured from one bracelet: its wearer is the louder voice.",
  context: "Who said what was worked out from the conversation itself.",
};

const STATUS_COPY: Record<Exclude<ConversationStatus, "ready">, (first: string) => [string, string]> = {
  not_recorded: (first) => [
    "Contact only",
    `One of you chose not to record, so there’s no AI summary. Voice notes you take about ${first} still show up here.`,
  ],
  processing: () => ["trO is writing your notes", "This takes about a minute after the conversation ends."],
  waiting_for_ai: () => ["Your conversation is saved", "Your notes will appear here as soon as trO processes it."],
  failed: () => ["Notes didn’t finish", "trO will try again before your summary email goes out."],
  expired: () => ["No notes for this one", "The recording was deleted with your summary email before notes could be made."],
};

function Transcript({ lines, first }: { lines: TranscriptLine[]; first: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex min-h-11 items-center justify-between text-left text-label font-medium text-highlight"
      >
        {open ? "Hide transcript" : `Show transcript · ${lines.length} lines`}
        <Icon icon={ChevronRight} size={20} className={cx("transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <ol className="flex flex-col gap-3">
          {lines.map((l, i) => (
            <li key={i} className="flex gap-3">
              <span
                className={cx(
                  "w-14 shrink-0 pt-px text-label-s font-semibold",
                  l.speaker === "you" ? "text-yellow" : l.speaker === "them" ? "text-highlight" : "text-highlight/50",
                )}
              >
                {l.speaker === "you" ? "You" : l.speaker === "them" ? first : "?"}
              </span>
              <span className="text-body text-highlight">{l.text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function VoiceNoteRow({ note }: { note: VoiceNote }) {
  const how = note.matched_by === "name" ? "You said their name" : note.matched_by === "ai" ? "Sorted by trO" : note.matched_by === "user" ? "Moved by you" : "";
  return (
    <li className="flex items-start gap-3">
      <IconBubble>
        <Mic />
      </IconBubble>
      <div className="flex flex-col gap-0.5">
        <p className="text-body text-highlight">{note.text}</p>
        <p className="text-caption text-highlight/50">{[time(note.recorded_at), how].filter(Boolean).join(" · ")}</p>
      </div>
    </li>
  );
}

export function NotesView({ data, back, sample = false }: { data: PersonNotes; back: { to: string; label: string }; sample?: boolean }) {
  const { person, conversation: convo } = data;
  const first = firstName(person.name);
  const subtitle = person.position ?? ([person.major, person.school].filter(Boolean).join(" · ") || null);
  const photo = api.mediaUrl(person.photo_url);
  const followUps = [...(convo?.follow_ups ?? []), ...data.voice_notes.flatMap((v) => (v.follow_up ? [v.follow_up] : []))];

  return (
    <Screen className="gap-6 pt-[31px] pb-10">
      <div className="relative flex items-center gap-3">
        <BackButton to={back.to} label={back.label} />
        {sample && <StatusPill icon={<Icon icon={Quote} />}>Sample conversation</StatusPill>}
      </div>

      <header className="relative flex flex-col gap-4">
        <div className="flex items-center gap-4">
          {photo ? (
            <img src={photo} alt="" className="size-16 shrink-0 rounded-full object-cover" />
          ) : (
            <span aria-hidden className="size-16 shrink-0 rounded-full bg-highlight/15" />
          )}
          <div className="flex min-w-0 flex-col gap-1 text-highlight">
            <DisplayTitle>{first}.</DisplayTitle>
            {subtitle && <p className="text-caption">{subtitle}</p>}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {person.recorded ? (
            <Badge tone="yellow" icon={<Icon icon={Mic} size={12} />}>Recorded</Badge>
          ) : (
            <Badge tone="glass">Contact only</Badge>
          )}
          {person.starred && <Badge tone="glass" icon={<Icon icon={Star} size={12} />}>Starred</Badge>}
        </div>
      </header>

      {convo ? (
        <>
          <Section title="What you talked about">
            <p className="text-body text-highlight">{convo.summary}</p>
            {convo.topics.length > 0 && (
              <ul className="flex flex-wrap gap-1.5">
                {convo.topics.map((t) => (
                  <li key={t}>
                    <Badge tone="glass">{t}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {convo.commitments.length > 0 && (
            <Section title="Promises">
              <ul className="flex flex-col gap-4">
                {convo.commitments.map((c, i) => (
                  <li key={i} className="flex flex-col gap-1.5">
                    <div className="flex items-start gap-2">
                      <Badge tone={c.who === "you" ? "yellow" : "glass"}>{c.who === "you" ? "You" : first}</Badge>
                      <p className="text-body text-highlight">{c.what}</p>
                    </div>
                    <p className="text-caption text-highlight/50">“{c.quote}”</p>
                  </li>
                ))}
              </ul>
              <p className="text-caption text-highlight/50">Every promise is checked word for word against the transcript.</p>
            </Section>
          )}
        </>
      ) : (
        <Empty title={STATUS_COPY[data.conversation_status as Exclude<ConversationStatus, "ready">]?.(first)[0] ?? "No notes yet"}>
          {STATUS_COPY[data.conversation_status as Exclude<ConversationStatus, "ready">]?.(first)[1] ?? ""}
        </Empty>
      )}

      {followUps.length > 0 && (
        <Section title="Follow up">
          <ul className="flex flex-col gap-3">
            {followUps.map((f, i) => (
              <li key={i} className="flex items-start gap-3 text-body text-highlight">
                <Icon icon={ArrowRight} className="mt-0.5 shrink-0 text-yellow" />
                {f}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {convo && convo.about_them.length > 0 && (
        <Section title={`About ${first}`}>
          <ul className="flex list-disc flex-col gap-1.5 pl-5 text-body text-highlight">
            {convo.about_them.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </Section>
      )}

      {data.voice_notes.length > 0 && (
        <Section title="Your voice notes">
          <ul className="flex flex-col gap-4">
            {data.voice_notes.map((v) => (
              <VoiceNoteRow key={v.id} note={v} />
            ))}
          </ul>
        </Section>
      )}

      {convo && convo.transcript.length > 0 && (
        <Card className="flex flex-col gap-2 p-5">
          <Transcript lines={convo.transcript} first={first} />
          <p className="text-caption text-highlight/50">{SPEAKER_METHOD[convo.speaker_method] ?? SPEAKER_METHOD.context}</p>
        </Card>
      )}

      <p className="text-caption text-highlight/50">Audio and transcripts are deleted after your summary email is sent.</p>
    </Screen>
  );
}

export default function PersonNotesScreen() {
  const { eventId } = useEventContext();
  const { userId: raw } = useParams();
  const userId = Number(raw);
  const [data, setData] = useState<PersonNotes | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);

  const load = useCallback(async () => {
    if (!eventId || !Number.isInteger(userId)) return;
    try {
      setData(await api.personNotes(eventId, userId));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setSignedOut(true);
      else setError(err instanceof ApiError ? err.message : "Couldn't load these notes.");
    }
  }, [eventId, userId]);

  useEffect(() => void load(), [load]);

  // Notes arrive about a minute after a conversation: keep checking until they're in.
  const waiting = data?.conversation_status === "processing" || data?.conversation_status === "waiting_for_ai";
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [waiting, load]);

  if (!eventId) return <Navigate to="/" replace />;
  if (signedOut) return <Navigate to={`/e/${eventId}`} replace />;
  const back = { to: `/e/${eventId}`, label: "Back to your connections" };
  if (error)
    return (
      <Screen className="gap-4 pt-[31px]">
        <div className="relative flex flex-col gap-4">
          <BackButton {...back} />
          <ErrorNote>{error}</ErrorNote>
        </div>
      </Screen>
    );
  if (!data) return <Screen><Loading label="Loading your notes" /></Screen>;
  return <NotesView data={data} back={back} />;
}

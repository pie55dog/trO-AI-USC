/**
 * Step 2 of 2: "Set your preferences".
 * Figma: "Refined / Set your preferences" (node 27:111).
 *
 * Both questions start unanswered: consent must be an explicit choice
 * (spec section 5), so "Finish setup" stays disabled until both are picked.
 * Finishing saves the answers, then links this phone's bracelet to the
 * attendee for this event.
 */

import { ChevronLeft, Mic, ShieldCheck, Users } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, ApiError, tokenStore } from "../api";
import { DisplayTitle, ErrorNote, IconBubble, Loading, PrimaryButton, Screen, StickyCta, YesNo } from "../components/ui";
import { useEventContext } from "../hooks";
import { braceletStore, draftStore } from "../session";

function Question({
  icon,
  title,
  note,
  value,
  onChange,
}: {
  icon: ReactNode;
  title: string;
  note: string;
  value: boolean | null;
  onChange: (v: boolean) => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-[20px] border border-line px-5 py-4">
      <div className="flex items-start gap-3">
        <IconBubble>{icon}</IconBubble>
        <div className="flex flex-col gap-1">
          <h2 className="text-body font-semibold">{title}</h2>
          <p className="text-caption text-ink-muted">{note}</p>
        </div>
      </div>
      <YesNo label={title} value={value} onChange={onChange} />
    </section>
  );
}

export default function Preferences() {
  const navigate = useNavigate();
  const { eventId, braceletId, eventName } = useEventContext();
  const [loading, setLoading] = useState(true);
  const [recording, setRecording] = useState<boolean | null>(null);
  const [recommendations, setRecommendations] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Show previous answers if the user comes back to change them.
  useEffect(() => {
    if (!tokenStore.get()) return;
    api
      .me()
      .then((me) => {
        setRecording(me.preferences.recording_consent);
        setRecommendations(me.preferences.recommendations_opt_in);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  // No account yet: step 1 comes first.
  if (!tokenStore.get()) return <Navigate to={`/e/${eventId}/welcome`} replace />;
  if (loading) return <Screen><Loading /></Screen>;

  const ready = recording !== null && recommendations !== null;

  const finish = async () => {
    if (recording === null || recommendations === null) return;
    setSaving(true);
    setError(null);
    try {
      const me = await api.savePreferences({ recording_consent: recording, recommendations_opt_in: recommendations });
      if (!me.onboarding.complete) {
        // Something in step 1 is still missing (e.g. cleared elsewhere).
        navigate(`/e/${eventId}/welcome`);
        return;
      }
      if (braceletId && eventId) {
        try {
          await api.claimBracelet(eventId, braceletId);
        } catch (err) {
          // Someone else already holds this bracelet (shared phone, swapped
          // bracelet, bad link). Setup is still done; forget the id so the
          // dashboard can say no bracelet is linked, and staff can fix it.
          if (!(err instanceof ApiError && err.status === 409)) throw err;
          braceletStore.clear(eventId);
        }
      }
      draftStore.set(null);
      navigate(`/e/${eventId}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save your preferences.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen className="gap-6">
      <div className="flex items-center justify-between">
        <Link to={`/e/${eventId}/welcome`} className="flex min-h-11 items-center gap-1 pr-2 text-body text-ink-body">
          <ChevronLeft aria-hidden className="size-5" />
          Profile
        </Link>
        <div className="flex items-center gap-1.5" aria-label="Step 2 of 2">
          <span className="text-caption text-ink-muted">Step 2 of 2</span>
          <span aria-hidden className="h-1 w-6 rounded-sm bg-ink" />
          <span aria-hidden className="h-1 w-6 rounded-sm bg-ink" />
        </div>
      </div>

      <section className="flex flex-col gap-4">
        <DisplayTitle>
          Welcome to
          <br />
          {eventName}.
        </DisplayTitle>
        <div className="flex flex-col gap-1">
          <h2 className="text-title font-semibold">Set your preferences</h2>
          <p className="text-body text-ink-muted">Pick one for each. You can change them until the event starts.</p>
        </div>
      </section>

      <Question
        icon={<Mic />}
        title="Do you consent to being recorded by trO when you connect with someone?"
        note="Only records if you both said yes. Your bracelet blinks the whole time."
        value={recording}
        onChange={setRecording}
      />
      <Question
        icon={<Users />}
        title="Do you want personalized connection recommendations based on your profile?"
        note="We suggest people to meet and include them in your summary."
        value={recommendations}
        onChange={setRecommendations}
      />

      <p className="flex items-start gap-2 text-caption text-ink-muted">
        <ShieldCheck aria-hidden className="size-4 shrink-0 text-ink" />
        Audio and transcripts are deleted after your summary email is sent.
      </p>

      {error && <ErrorNote>{error}</ErrorNote>}

      <StickyCta>
        <PrimaryButton onClick={finish} disabled={!ready} loading={saving}>
          Finish setup
        </PrimaryButton>
        <p className="text-center text-caption text-ink-muted">
          {ready ? "You can change these until the event starts." : "Both questions need an answer to finish."}
        </p>
      </StickyCta>
    </Screen>
  );
}

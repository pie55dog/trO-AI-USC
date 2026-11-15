/**
 * Step 2 of 2: "Set your preferences".
 * Figma: "Refined / Set your preferences (Dark)" on Page 1 ("final").
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
import { Card, DisplayTitle, ErrorNote, Icon, IconBubble, Loading, PrimaryButton, Screen, StepIndicator, StickyCta, YesNo } from "../components/ui";
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
    <Card className="flex flex-col gap-3 px-5 py-4">
      <div className="flex items-start gap-3">
        <IconBubble>{icon}</IconBubble>
        <div className="flex flex-col gap-1 text-highlight">
          <h2 className="text-label font-medium">{title}</h2>
          <p className="text-caption">{note}</p>
        </div>
      </div>
      <YesNo label={title} value={value} onChange={onChange} />
    </Card>
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
    <Screen className="gap-6 pt-7">
      <div className="relative flex items-center justify-between">
        <Link to={`/e/${eventId}/welcome`} className="flex min-h-11 items-center gap-1 pr-2 text-body text-highlight">
          <Icon icon={ChevronLeft} size={20} />
          Profile
        </Link>
        <StepIndicator step={2} />
      </div>

      <section className="relative flex flex-col gap-4">
        <DisplayTitle>
          Welcome to
          <br />
          {eventName}.
        </DisplayTitle>
        <h2 className="text-body text-highlight">Set your preferences</h2>
      </section>

      <Question
        icon={<Icon icon={Mic} size={20} />}
        title="Do you consent to being recorded by trO when you connect with someone?"
        note="Only records if you both said yes. Your bracelet blinks the whole time."
        value={recording}
        onChange={setRecording}
      />
      <Question
        icon={<Icon icon={Users} size={20} />}
        title="Do you want personalized connection recommendations based on your profile?"
        note="We suggest people to meet and include them in your summary."
        value={recommendations}
        onChange={setRecommendations}
      />

      <p className="flex items-start gap-2 text-caption text-highlight">
        <Icon icon={ShieldCheck} />
        Audio and transcripts are deleted after your summary email is sent.
      </p>

      {error && <ErrorNote>{error}</ErrorNote>}

      <StickyCta pushDown={false}>
        <PrimaryButton onClick={finish} disabled={!ready} loading={saving}>
          Finish setup
        </PrimaryButton>
      </StickyCta>
    </Screen>
  );
}

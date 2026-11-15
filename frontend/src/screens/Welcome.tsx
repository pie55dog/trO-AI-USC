/**
 * Step 1 of 2: "Welcome to event." Summary email + profile.
 * Figma: "Refined / Welcome to event" (node 27:2).
 *
 * "Continue" creates the account from name + email. If the phone already has
 * a token (signed in earlier), the saved profile fills any empty fields.
 * What the user typed is saved as a draft, so a reload never loses it.
 */

import { Camera, Mail, Plus, Watch } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, tokenStore, type Me } from "../api";
import {
  Chip,
  DisplayTitle,
  ErrorNote,
  Field,
  LinkedinIcon,
  Loading,
  PrimaryButton,
  Screen,
  SecondaryButton,
  StatusPill,
  StickyCta,
} from "../components/ui";
import { useEventContext, wordCount } from "../hooks";
import { draftStore, emptyDraft, type ProfileDraft } from "../session";

export const INTEREST_OPTIONS = ["AI & ML", "Startups", "Design", "Finance", "Research", "Consulting"];
const BIO_MAX = 20;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Errors = Partial<Record<keyof ProfileDraft, string>>;

/** Required-field checks, mirroring the backend's onboarding rules. */
export function validate(d: ProfileDraft): Errors {
  const e: Errors = {};
  if (!d.name.trim()) e.name = "Add your name.";
  if (!EMAIL_RE.test(d.email.trim())) e.email = "Enter a valid email so your summary reaches you.";
  if (!d.school.trim()) e.school = "Add your school.";
  if (!d.major.trim()) e.major = "Add your major.";
  const words = wordCount(d.bio);
  // Bio is optional: no minimum, just a cap so it fits on a card.
  if (words > BIO_MAX) e.bio = `Keep it to ${BIO_MAX} words or fewer.`;
  if (d.interests.length === 0) e.interests = "Pick at least one.";
  return e;
}

/** Fill only the fields the user left empty with what the server knows. */
function mergeServer(draft: ProfileDraft, me: Me): ProfileDraft {
  const p = me.profile;
  const pick = (mine: string, theirs: string | null) => (mine.trim() ? mine : theirs ?? "");
  return {
    name: pick(draft.name, p.name),
    email: pick(draft.email, p.email),
    school: pick(draft.school, p.school),
    major: pick(draft.major, p.major),
    bio: pick(draft.bio, p.bio),
    position: pick(draft.position, p.position),
    interests: draft.interests.length ? draft.interests : p.interests,
    linkedin_url: pick(draft.linkedin_url, p.linkedin_url),
    portfolio_url: pick(draft.portfolio_url, p.portfolio_url),
    website: pick(draft.website, p.website),
    instagram: pick(draft.instagram, p.instagram),
  };
}

export default function Welcome() {
  const navigate = useNavigate();
  const { eventId, braceletId, eventName } = useEventContext();
  const fileInput = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>(() => draftStore.get() ?? emptyDraft);
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  // A photo picked before the account exists; uploaded on Continue.
  const [pendingPhoto, setPendingPhoto] = useState<File | null>(null);
  const [showMoreLinks, setShowMoreLinks] = useState(false);
  const [otherInterest, setOtherInterest] = useState<string | null>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Load the account if we have a token (e.g. signed in earlier).
  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then((me) => {
        setSignedIn(true);
        setDraft((d) => mergeServer(d, me));
        setPhotoUrl(api.mediaUrl(me.profile.photo_url));
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setSignedIn(false); // token expired and was cleared: continue as a new user
        } else {
          // Still signed in, just couldn't load (e.g. flaky Wi-Fi). Don't
          // treat it as signed out, or Continue would create a second account.
          setSignedIn(true);
          setSubmitError(err instanceof ApiError ? err.message : "Couldn't load your profile.");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  // Keep the draft so nothing is lost if the page reloads.
  useEffect(() => draftStore.set(draft), [draft]);

  // Preview for a photo picked before the account exists.
  const pendingPreview = useMemo(() => (pendingPhoto ? URL.createObjectURL(pendingPhoto) : null), [pendingPhoto]);
  useEffect(() => () => void (pendingPreview && URL.revokeObjectURL(pendingPreview)), [pendingPreview]);

  const hasExtraLinks = !!(draft.portfolio_url || draft.website || draft.instagram);
  const set = <K extends keyof ProfileDraft>(key: K, value: ProfileDraft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }));
  };

  const toggleInterest = (name: string) =>
    set("interests", draft.interests.includes(name) ? draft.interests.filter((i) => i !== name) : [...draft.interests, name]);

  const addOther = () => {
    const value = (otherInterest ?? "").trim();
    if (value && !draft.interests.some((i) => i.toLowerCase() === value.toLowerCase())) {
      set("interests", [...draft.interests, value]);
    }
    setOtherInterest(null);
  };

  const onPickPhoto = async (file: File | undefined) => {
    if (!file) return;
    setSubmitError(null);
    if (!signedIn) {
      setPendingPhoto(file);
      return;
    }
    try {
      const me = await api.uploadPhoto(file);
      setPhotoUrl(api.mediaUrl(me.profile.photo_url));
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Couldn't upload that photo.");
    }
  };

  const onSubmit = async (ev: FormEvent) => {
    ev.preventDefault();
    const found = validate(draft);
    setErrors(found);
    if (Object.keys(found).length) {
      // Bring the first problem into view once React has rendered the errors.
      requestAnimationFrame(() =>
        document.querySelector("[aria-invalid='true']")?.scrollIntoView({ block: "center", behavior: "smooth" }),
      );
      return;
    }
    setSaving(true);
    setSubmitError(null);
    try {
      if (!signedIn) {
        const { token } = await api.signUp(draft.name.trim(), draft.email.trim());
        tokenStore.set(token);
        setSignedIn(true);
      }
      // Empty optional fields are sent as null so clearing them works.
      const opt = (v: string) => (v.trim() ? v.trim() : null);
      await api.updateProfile({
        name: draft.name.trim(),
        email: draft.email.trim(),
        school: draft.school.trim(),
        major: draft.major.trim(),
        bio: draft.bio.trim(),
        position: opt(draft.position),
        interests: draft.interests,
        linkedin_url: opt(draft.linkedin_url),
        portfolio_url: opt(draft.portfolio_url),
        website: opt(draft.website),
        instagram: opt(draft.instagram),
      });
      if (pendingPhoto) {
        await api.uploadPhoto(pendingPhoto);
        setPendingPhoto(null);
      }
      navigate(`/e/${eventId}/preferences`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setErrors((e) => ({ ...e, email: "This email already has an account. Use another one." }));
      } else {
        setSubmitError(err instanceof ApiError ? err.message : "Couldn't save your profile.");
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Screen><Loading /></Screen>;

  const words = wordCount(draft.bio);
  const shownPhoto = pendingPreview ?? photoUrl;

  return (
    <Screen>
      <form onSubmit={onSubmit} noValidate className="flex flex-1 flex-col gap-8">
        {braceletId && <StatusPill icon={<Watch />}>Bracelet {braceletId} linked to this phone</StatusPill>}

        <section className="flex flex-col gap-3">
          <DisplayTitle>
            Welcome to
            <br />
            {eventName}.
          </DisplayTitle>
          <p className="text-body text-ink-body">
            You’re using trO, a smart wristband that helps you keep your connections with the Trojan family.
          </p>
        </section>

        <section className="flex flex-col gap-3 rounded-[20px] bg-soft p-5">
          <div className="flex items-start gap-3">
            <Mail aria-hidden className="size-5 shrink-0" />
            <p className="text-body font-semibold">
              After the event, you’ll get one email with everyone you connected with: contact info, bios, and how to
              follow up.
            </p>
          </div>
          <Field
            label="Send my summary to"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="ttrojan@usc.edu"
            value={draft.email}
            onChange={(e) => set("email", e.target.value)}
            hint="Use your USC email if you have one."
            error={errors.email}
          />
        </section>

        <section className="flex flex-col gap-6">
          <header className="flex flex-col gap-1">
            <h2 className="text-title font-semibold">Build your profile</h2>
            <p className="text-body text-ink-muted">This is what gets sent to the people you connect with.</p>
          </header>

          <Field
            label="Name"
            autoComplete="name"
            placeholder="Tommy Trojan"
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
            error={errors.name}
          />
          <div className="flex gap-3">
            <Field
              className="flex-1"
              label="School"
              placeholder="Viterbi"
              value={draft.school}
              onChange={(e) => set("school", e.target.value)}
              error={errors.school}
            />
            <Field
              className="flex-1"
              label="Major"
              placeholder="Comp. Sci."
              value={draft.major}
              onChange={(e) => set("major", e.target.value)}
              error={errors.major}
            />
          </div>
          <Field
            multiline
            label={`Bio (optional) · up to ${BIO_MAX} words`}
            placeholder="Junior building tools for student orgs. Into AI and hackathons."
            value={draft.bio}
            onChange={(e) => set("bio", e.target.value)}
            hint={`${words} of ${BIO_MAX} words`}
            error={errors.bio}
          />
          <Field
            label="Current position · optional"
            placeholder="e.g. SWE intern at Snap"
            value={draft.position}
            onChange={(e) => set("position", e.target.value)}
          />

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-caption font-semibold">Interests</legend>
            <div className="flex flex-wrap gap-2">
              {[...INTEREST_OPTIONS, ...draft.interests.filter((i) => !INTEREST_OPTIONS.includes(i))].map((name) => (
                <Chip key={name} selected={draft.interests.includes(name)} onClick={() => toggleInterest(name)}>
                  {name}
                </Chip>
              ))}
              {otherInterest === null ? (
                <Chip onClick={() => setOtherInterest("")}>+ Other</Chip>
              ) : (
                <input
                  autoFocus
                  aria-label="Other interest"
                  placeholder="Type and press enter"
                  value={otherInterest}
                  onChange={(e) => setOtherInterest(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addOther();
                    }
                  }}
                  onBlur={addOther}
                  className="min-h-11 rounded-full border border-ink px-4 text-caption"
                />
              )}
            </div>
            <p className={errors.interests ? "text-caption text-danger" : "text-caption text-ink-muted"}>
              {errors.interests ?? "Pick a few. They help match you with people you’d click with."}
            </p>
          </fieldset>

          <section className="flex flex-col gap-2">
            <h3 className="text-caption font-semibold">Links · optional</h3>
            <div className="flex items-center gap-2">
              <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-full bg-soft">
                <LinkedinIcon className="size-5" />
              </span>
              <input
                aria-label="LinkedIn profile"
                inputMode="url"
                placeholder="linkedin.com/in/tommytrojan"
                value={draft.linkedin_url}
                onChange={(e) => set("linkedin_url", e.target.value)}
                className="min-w-0 flex-1 rounded-xl border border-line px-4 py-[13px] text-body placeholder:text-ink-muted"
              />
            </div>
            {showMoreLinks || hasExtraLinks ? (
              <div className="flex flex-col gap-4 pt-2">
                <Field label="Portfolio" inputMode="url" placeholder="behance.net/you" value={draft.portfolio_url} onChange={(e) => set("portfolio_url", e.target.value)} />
                <Field label="Website" inputMode="url" placeholder="you.dev" value={draft.website} onChange={(e) => set("website", e.target.value)} />
                <Field label="Instagram" placeholder="@tommytrojan" value={draft.instagram} onChange={(e) => set("instagram", e.target.value)} />
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowMoreLinks(true)}
                className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line py-[13px] text-body font-semibold"
              >
                <Plus aria-hidden className="size-4" />
                Add portfolio, website, or Instagram
              </button>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex items-center gap-4">
              {shownPhoto ? (
                <img src={shownPhoto} alt="Your photo" className="size-[66px] shrink-0 rounded-full object-cover" />
              ) : (
                <span aria-hidden className="flex size-[66px] shrink-0 items-center justify-center rounded-full border border-dashed border-ink-muted bg-soft">
                  <Camera className="size-6" />
                </span>
              )}
              <div className="flex flex-col gap-0.5">
                <p className="text-body font-semibold">{shownPhoto ? "Looking good" : "Add a photo"}</p>
                <p className="text-caption text-ink-muted">This helps people remember you.</p>
              </div>
            </div>
            <div className="flex gap-2">
              <SecondaryButton type="button" onClick={() => fileInput.current?.click()}>
                {shownPhoto ? "Change photo" : "Upload photo"}
              </SecondaryButton>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(e) => {
                void onPickPhoto(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </section>
        </section>

        {submitError && <ErrorNote>{submitError}</ErrorNote>}

        <StickyCta divider>
          <PrimaryButton type="submit" loading={saving}>
            Continue
          </PrimaryButton>
          <p className="text-center text-caption text-ink-muted">Step 1 of 2 · Takes about 2 minutes</p>
        </StickyCta>
      </form>
    </Screen>
  );
}

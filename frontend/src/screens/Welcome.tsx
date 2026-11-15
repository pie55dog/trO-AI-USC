/**
 * Step 1 of 2: "Welcome to event." Summary email + profile.
 * Figma: "Refined / Welcome to event (Dark)" on Page 1 ("final").
 *
 * "Continue" creates the account from name + email. If the phone already has
 * a token (signed in earlier), the saved profile fills any empty fields.
 * What the user typed is saved as a draft, so a reload never loses it.
 */

import { Camera, Mail, Plus, Watch } from "lucide-react";
import summaryCard from "../assets/summary-card.png";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, tokenStore, type Me } from "../api";
import {
  Button,
  Chip,
  DisplayTitle,
  ErrorNote,
  Field,
  Icon,
  inputClass,
  LinkedinIcon,
  Loading,
  PrimaryButton,
  Screen,
  StatusPill,
  StepIndicator,
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

  const shownPhoto = pendingPreview ?? photoUrl;

  return (
    <Screen className="pt-[31px]">
      <form onSubmit={onSubmit} noValidate className="relative flex flex-1 flex-col gap-8">
        <div className="flex items-center justify-between gap-2">
          {braceletId ? (
            <StatusPill icon={<Icon icon={Watch} />}>Bracelet {braceletId} linked</StatusPill>
          ) : (
            <span />
          )}
          <StepIndicator step={1} />
        </div>

        <section className="flex flex-col gap-3">
          <DisplayTitle>
            Welcome to
            <br />
            {eventName}.
          </DisplayTitle>
          <p className="text-body text-highlight">
            You’re using trO, a smart wristband that helps you keep your connections with the Trojan family.
          </p>
        </section>

        <section className="glass relative flex flex-col gap-3 overflow-hidden rounded-[20px] p-5">
          <img aria-hidden src={summaryCard} alt="" className="pointer-events-none absolute inset-0 size-full object-cover opacity-40" />
          <div className="relative flex items-start gap-3">
            <Icon icon={Mail} size={20} />
            <p className="text-label font-medium text-highlight">
              After the event, you’ll get one email with everyone you connected with: contact info, bios, and how to
              follow up.
            </p>
          </div>
          <Field
            className="relative"
            label="Send my summary to"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="ttrojan@usc.edu"
            value={draft.email}
            onChange={(e) => set("email", e.target.value)}
            error={errors.email}
          />
        </section>

        <section className="flex flex-col gap-6">
          <header className="flex flex-col gap-1 text-highlight">
            <h2 className="text-title font-semibold">Build your profile</h2>
            <p className="text-body">This is what gets sent to the people you connect with.</p>
          </header>

          <Field
            label="Name"
            autoComplete="name"
            placeholder="e.g. Tommy Trojan"
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
            error={errors.name}
          />
          <div className="flex gap-3">
            <Field
              className="flex-1"
              label="School"
              value={draft.school}
              onChange={(e) => set("school", e.target.value)}
              error={errors.school}
            />
            <Field
              className="flex-1"
              label="Major"
              value={draft.major}
              onChange={(e) => set("major", e.target.value)}
              error={errors.major}
            />
          </div>
          <Field
            multiline
            label={`Bio · 5–${BIO_MAX} words · optional`}
            value={draft.bio}
            onChange={(e) => set("bio", e.target.value)}
            error={errors.bio}
          />
          <Field
            label="Current position · optional"
            placeholder="e.g. SWE intern at Snap"
            value={draft.position}
            onChange={(e) => set("position", e.target.value)}
          />

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-label-s font-semibold">Interests</legend>
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
                  className="min-h-10 rounded-full border border-highlight bg-[rgb(27_24_25/0.2)] px-4 text-caption text-highlight placeholder:text-highlight/45"
                />
              )}
            </div>
            {errors.interests && <p className="text-caption text-danger">{errors.interests}</p>}
          </fieldset>

          <section className="flex flex-col gap-2">
            <h3 className="text-label-s font-semibold">Links · optional</h3>
            <div className="flex items-center gap-2">
              <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-full bg-highlight/[0.08] text-highlight">
                <LinkedinIcon size={20} />
              </span>
              <input
                aria-label="LinkedIn profile"
                inputMode="url"
                placeholder="e.g. linkedin.com/in/tommytrojan"
                value={draft.linkedin_url}
                onChange={(e) => set("linkedin_url", e.target.value)}
                className={inputClass()}
              />
            </div>
            {showMoreLinks || hasExtraLinks ? (
              <div className="flex flex-col gap-4 pt-2">
                <Field label="Portfolio" inputMode="url" placeholder="e.g. behance.net/you" value={draft.portfolio_url} onChange={(e) => set("portfolio_url", e.target.value)} />
                <Field label="Website" inputMode="url" placeholder="e.g. you.dev" value={draft.website} onChange={(e) => set("website", e.target.value)} />
                <Field label="Instagram" placeholder="e.g. @tommytrojan" value={draft.instagram} onChange={(e) => set("instagram", e.target.value)} />
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowMoreLinks(true)}
                className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-dashed border-highlight/30 bg-highlight/[0.06] py-[13px] text-label font-medium text-highlight/85"
              >
                <Icon icon={Plus} />
                Add portfolio, website, or Instagram
              </button>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex items-center gap-4">
              {shownPhoto ? (
                <img src={shownPhoto} alt="Your photo" className="size-[66px] shrink-0 rounded-full object-cover" />
              ) : (
                <span aria-hidden className="flex size-[66px] shrink-0 items-center justify-center rounded-full border border-dashed border-highlight/20 bg-highlight/10">
                  <Icon icon={Camera} size={24} />
                </span>
              )}
              <p className="text-label font-medium text-highlight">{shownPhoto ? "Looking good" : "Add a photo"}</p>
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="soft" className="flex-1" onClick={() => fileInput.current?.click()}>
                {shownPhoto ? "Change photo" : "Upload photo"}
              </Button>
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
        </StickyCta>
      </form>
    </Screen>
  );
}


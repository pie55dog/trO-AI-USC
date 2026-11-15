/**
 * Preview mode: the app running with no backend, e.g. on GitHub Pages for
 * phone testing before an API is hosted.
 *
 * It stands in for the endpoints the screens call, keeping everything on this
 * phone (localStorage). It never invents data: there are no fake events or
 * connections, so the dashboard shows its real empty states. Rules mirror the
 * backend (see backend/app/routers/users.py) so the flow behaves the same.
 */

import type { BraceletAssignment, Connection, EventInfo, EventNotes, Me, PersonNotes, Preferences, Profile, ProfileUpdate, ShareableField } from "./api";
import { ApiError, storageGet, storageSet } from "./api";

const STATE_KEY = "tro.preview";
export const PREVIEW_TOKEN = "preview";

const SHAREABLE: ShareableField[] = ["email", "linkedin_url", "company", "website", "portfolio_url", "instagram"];
const REQUIRED: (keyof Profile)[] = ["name", "email", "school", "major", "interests"];

interface State {
  profile: Profile;
  preferences: Preferences;
  bracelets: Record<string, BraceletAssignment>;
}

function load(): State | null {
  try {
    const raw = storageGet(STATE_KEY);
    return raw ? (JSON.parse(raw) as State) : null;
  } catch {
    return null;
  }
}

function save(state: State): void {
  storageSet(STATE_KEY, JSON.stringify(state));
}

function requireState(): State {
  const state = load();
  if (!state || storageGet("tro.token") !== PREVIEW_TOKEN) throw new ApiError(401, "Sign in required");
  return state;
}

function toMe(state: State): Me {
  const missing: string[] = REQUIRED.filter((f) => {
    const v = state.profile[f];
    return Array.isArray(v) ? v.length === 0 : !v;
  });
  if (state.preferences.recording_consent === null) missing.push("recording_consent");
  if (state.preferences.recommendations_opt_in === null) missing.push("recommendations_opt_in");
  return { profile: state.profile, preferences: state.preferences, onboarding: { complete: !missing.length, missing } };
}

const nowIso = () => new Date().toISOString();
const resolved = <T>(value: T) => Promise.resolve(value);

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new ApiError(400, "Couldn't read that photo."));
    reader.readAsDataURL(file);
  });
}

export const previewApi = {
  signUp: async (name: string, email: string) => {
    const state: State = {
      profile: {
        id: 1,
        name,
        email,
        school: null,
        major: null,
        bio: null,
        interests: [],
        position: null,
        linkedin_url: null,
        company: null,
        website: null,
        portfolio_url: null,
        instagram: null,
        photo_url: null,
      },
      preferences: {
        recording_consent: null,
        recording_consent_updated_at: null,
        recommendations_opt_in: null,
        summary_email_opt_in: true,
        shared_fields: [...SHAREABLE],
      },
      bracelets: {},
    };
    save(state);
    return { token: PREVIEW_TOKEN, me: toMe(state) };
  },

  me: async () => toMe(requireState()),

  updateProfile: async (changes: ProfileUpdate) => {
    const state = requireState();
    state.profile = { ...state.profile, ...changes };
    save(state);
    return toMe(state);
  },

  savePreferences: async (prefs: {
    recording_consent: boolean;
    recommendations_opt_in: boolean;
    summary_email_opt_in?: boolean;
    shared_fields?: ShareableField[];
  }) => {
    const state = requireState();
    const consentChanged = state.preferences.recording_consent !== prefs.recording_consent;
    state.preferences = {
      ...state.preferences,
      ...prefs,
      recording_consent_updated_at: consentChanged ? nowIso() : state.preferences.recording_consent_updated_at,
    };
    save(state);
    return toMe(state);
  },

  uploadPhoto: async (file: File) => {
    const state = requireState();
    state.profile.photo_url = await readAsDataUrl(file);
    save(state);
    return toMe(state);
  },

  // There is no event list without a backend; screens fall back to "event".
  event: (_id: number): Promise<EventInfo> => Promise.reject(new ApiError(404, "Event not found")),

  claimBracelet: async (eventId: number, braceletId: string) => {
    const state = requireState();
    const me = toMe(state);
    if (!me.onboarding.complete) throw new ApiError(409, "Finish setting up your profile first", me.onboarding);
    const assignment = { event_id: eventId, bracelet_id: braceletId, assigned_at: nowIso() };
    state.bracelets[String(eventId)] = assignment;
    save(state);
    return assignment;
  },

  myBracelet: async (eventId: number) => {
    const found = requireState().bracelets[String(eventId)];
    if (!found) throw new ApiError(404, "No bracelet linked for this event");
    return found;
  },

  // Connections come from bracelet taps, which need the backend.
  connections: (_eventId: number) => {
    requireState();
    return resolved<Connection[]>([]);
  },

  // Notes come from recordings, which need the backend.
  notes: (_eventId: number) => {
    requireState();
    return resolved<EventNotes>({ people: [], other: [], voice_notes_processing: 0 });
  },
  personNotes: (_eventId: number, _userId: number): Promise<PersonNotes> =>
    Promise.reject(new ApiError(404, "Notes need the trO server. This preview has none.")),

  // Recordings are transcribed on the server.
  uploadRecording: (): Promise<never> =>
    Promise.reject(new ApiError(503, "Recording needs the trO server. This preview has none.")),

  watchCode: (): Promise<never> =>
    Promise.reject(new ApiError(503, "Pairing a watch needs the trO server. This preview has none.")),

  // Sending email needs the real server (scripts/local-server.sh).
  testEmail: (_eventId: number): Promise<{ sent_to: string; delivered: boolean }> =>
    Promise.reject(new ApiError(503, "Sending email needs the trO server. This preview has none.")),
};

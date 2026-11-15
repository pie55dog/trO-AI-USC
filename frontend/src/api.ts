/**
 * Thin client for the Tro backend (see backend/README.md for every endpoint).
 *
 * The login token lives in localStorage and is sent as a Bearer header.
 * Every function throws ApiError with the server's message on failure, so
 * screens can show it directly.
 */

import { previewApi } from "./preview";

const CONFIGURED_API = import.meta.env.VITE_API_URL ?? "";

/**
 * A production build with no API configured (e.g. GitHub Pages before a
 * backend is hosted) runs in preview mode: see preview.ts.
 */
export const PREVIEW = import.meta.env.PROD && !CONFIGURED_API;

export const API_URL = (CONFIGURED_API || "http://localhost:8000").replace(/\/$/, "");

// --- Types (mirror backend/app/schemas.py) ---------------------------------

export type ShareableField = "email" | "linkedin_url" | "company" | "website" | "portfolio_url" | "instagram";

export interface Profile {
  id: number;
  name: string;
  email: string | null;
  school: string | null;
  major: string | null;
  bio: string | null;
  interests: string[];
  position: string | null;
  linkedin_url: string | null;
  company: string | null;
  website: string | null;
  portfolio_url: string | null;
  instagram: string | null;
  photo_url: string | null;
}

export interface Preferences {
  recording_consent: boolean | null;
  recording_consent_updated_at: string | null;
  recommendations_opt_in: boolean | null;
  summary_email_opt_in: boolean;
  shared_fields: ShareableField[];
}

export interface Me {
  profile: Profile;
  preferences: Preferences;
  onboarding: { complete: boolean; missing: string[] };
}

export interface EventInfo {
  id: number;
  name: string;
  location: string | null;
  starts_at: string | null;
}

export interface BraceletAssignment {
  event_id: number;
  bracelet_id: string;
  assigned_at: string;
}

export interface Connection {
  user_id: number;
  /** The tap. The phone mic uploads its clip against this. Older servers leave it out. */
  connection_id?: number;
  name: string;
  position: string | null;
  school: string | null;
  major: string | null;
  bio: string | null;
  photo_url: string | null;
  recorded: boolean;
  /** Both people currently say yes to recording (the phone mic only records then). */
  both_consented?: boolean;
  // Starred from the bracelet (short button press).
  starred?: boolean;
  contact: Partial<Record<ShareableField, string>>;
  tapped_at: string;
  /** What the "Conversation notes" line on the card says. Older servers leave it out. */
  notes?: NotesPreview;
}

/** not_recorded: contact only. processing / waiting_for_ai: audio in, notes not yet. */
export type ConversationStatus = "not_recorded" | "processing" | "waiting_for_ai" | "ready" | "failed" | "expired";

export interface NotesPreview {
  conversation: ConversationStatus;
  voice_notes: number;
  follow_ups: number;
}

export interface Commitment {
  who: "you" | "them";
  what: string;
  /** The exact words from the transcript the promise was checked against. */
  quote: string;
}

export interface TranscriptLine {
  speaker: "you" | "them" | "unsure";
  text: string;
  start: number;
}

export interface ConversationNotes {
  summary: string;
  topics: string[];
  about_them: string[];
  commitments: Commitment[];
  follow_ups: string[];
  /** Empty once the summary email has gone out (transcripts are deleted). */
  transcript: TranscriptLine[];
  speaker_method: "two_bracelets" | "one_bracelet" | "context" | string;
  updated_at: string;
}

export interface VoiceNote {
  id: number;
  category: "person" | "idea" | "task" | "other";
  text: string;
  follow_up: string | null;
  matched_by: "name" | "ai" | "user" | "";
  recorded_at: string;
  person_user_id: number | null;
  person_name: string | null;
}

export interface PersonNotes {
  person: Connection;
  conversation_status: ConversationStatus;
  conversation: ConversationNotes | null;
  voice_notes: VoiceNote[];
}

export interface EventNotes {
  people: PersonNotes[];
  other: VoiceNote[];
  voice_notes_processing: number;
}

export interface RecordingResult {
  id: number;
  kind: string;
  status: string;
  connection_id: number | null;
  duration_s: number | null;
}

export type ProfileUpdate = Partial<Omit<Profile, "id" | "photo_url">>;

// --- Token storage ------------------------------------------------------------

const TOKEN_KEY = "tro.token";

/** localStorage can throw (private mode, blocked storage); never let that crash the app. */
function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export const tokenStore = {
  get: () => storageGet(TOKEN_KEY),
  set: (token: string | null) => storageSet(TOKEN_KEY, token),
};

export { storageGet, storageSet };

// --- Requests -------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  /** Extra detail the server sent, e.g. onboarding's `missing` list. */
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** Turn FastAPI's error body into one readable sentence. */
function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return capitalize(detail);
  if (detail && typeof detail === "object" && "message" in detail) return capitalize(String(detail.message));
  if (Array.isArray(detail) && detail[0]?.msg) {
    // Validation errors: "body.email: value is not a valid email address"
    const first = detail[0] as { loc?: unknown[]; msg: string };
    const field = first.loc?.[first.loc.length - 1];
    return capitalize(field ? `${String(field).replace(/_/g, " ")}: ${first.msg}` : first.msg);
  }
  if (status === 0) return "Can't reach trO right now. Check your connection and try again.";
  return "Something went wrong. Please try again.";
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * The free backend host sleeps after 15 idle minutes and takes up to a minute
 * to wake. Pinging it as soon as the app opens starts that wake-up while the
 * person is still reading the first screen.
 */
export function wakeServer(): void {
  if (!PREVIEW) fetch(`${API_URL}/health`).catch(() => undefined);
}

const ADMIN_KEY = "tro.adminKey";

/** The organizer key (X-Admin-Key) the organizer console signed in with. */
export const adminKeyStore = {
  get: () => storageGet(ADMIN_KEY),
  set: (key: string | null) => storageSet(ADMIN_KEY, key),
};

/**
 * `auth: "admin"` sends the organizer key instead of the attendee login, for
 * the organizer console (see organizerApi.ts).
 */
export async function request<T>(path: string, init: RequestInit = {}, auth: "user" | "admin" = "user"): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth === "admin") {
    const key = adminKeyStore.get();
    if (key) headers.set("X-Admin-Key", key);
  } else {
    const token = tokenStore.get();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  // JSON bodies are strings; FormData and audio Blobs set their own type.
  if (typeof init.body === "string" && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  let resp: Response;
  try {
    resp = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, errorMessage(0, null));
  }
  if (resp.status === 204) return undefined as T;
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    // Expired or deleted account, or an organizer key that was changed.
    if (resp.status === 401) (auth === "admin" ? adminKeyStore : tokenStore).set(null);
    throw new ApiError(resp.status, errorMessage(resp.status, body), (body as { detail?: unknown })?.detail);
  }
  return body as T;
}

const serverApi = {
  /** Full-page redirect target that starts LinkedIn sign-in. */
  linkedinLoginUrl: () => `${API_URL}/auth/linkedin/login`,
  /** Absolute URL for a photo path returned by the API (preview mode stores data: URLs). */
  mediaUrl: (path: string | null) => (path ? (path.startsWith("data:") ? path : `${API_URL}${path}`) : null),

  signUp: (name: string, email: string) =>
    request<{ token: string; me: Me }>("/users", { method: "POST", body: JSON.stringify({ name, email }) }),
  me: () => request<Me>("/users/me"),
  updateProfile: (changes: ProfileUpdate) =>
    request<Me>("/users/me", { method: "PATCH", body: JSON.stringify(changes) }),
  savePreferences: (prefs: {
    recording_consent: boolean;
    recommendations_opt_in: boolean;
    summary_email_opt_in?: boolean;
    shared_fields?: ShareableField[];
  }) => request<Me>("/users/me/preferences", { method: "PUT", body: JSON.stringify(prefs) }),
  uploadPhoto: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Me>("/users/me/photo", { method: "POST", body: form });
  },

  event: (id: number) => request<EventInfo>(`/events/${id}`),
  claimBracelet: (eventId: number, braceletId: string) =>
    request<BraceletAssignment>(`/events/${eventId}/bracelet`, {
      method: "POST",
      body: JSON.stringify({ bracelet_id: braceletId }),
    }),
  myBracelet: (eventId: number) => request<BraceletAssignment>(`/events/${eventId}/bracelet`),
  connections: (eventId: number) => request<Connection[]>(`/events/${eventId}/connections`),
  /** Everything the signed-in person noted at this event. */
  notes: (eventId: number) => request<EventNotes>(`/events/${eventId}/notes`),
  /** One person they met: AI summary, promises, follow-ups, their voice notes. */
  personNotes: (eventId: number, userId: number) => request<PersonNotes>(`/events/${eventId}/notes/${userId}`),
  /**
   * One clip from the phone mic (screens/PhoneMic.tsx): raw 16 kHz WAV.
   * `startedAt` is Unix ms from the phone's clock. 403 = one of you said no to recording.
   */
  uploadRecording: (
    eventId: number,
    wav: Blob,
    params: { kind: "conversation" | "voice_note"; connectionId?: number; startedAt?: number },
  ) => {
    const q = new URLSearchParams({ kind: params.kind });
    if (params.connectionId !== undefined) q.set("connection_id", String(params.connectionId));
    if (params.startedAt !== undefined) q.set("started_at", String(Math.round(params.startedAt)));
    return request<RecordingResult>(`/events/${eventId}/recordings?${q}`, {
      method: "POST",
      body: wav,
      headers: { "Content-Type": "audio/wav" },
    });
  },
  /** A one-time 6-digit code that signs the trO Apple Watch app in (5 minutes, single use). */
  watchCode: (eventId: number) =>
    request<{ code: string; expires_at: string }>(`/events/${eventId}/watch-code`, { method: "POST" }),
  /** Email the signed-in person their summary for this event right now. */
  testEmail: (eventId: number) => request<{ sent_to: string; delivered: boolean }>(`/events/${eventId}/test-email`, { method: "POST" }),
};

export const api: typeof serverApi = PREVIEW ? { ...serverApi, ...previewApi } : serverApi;

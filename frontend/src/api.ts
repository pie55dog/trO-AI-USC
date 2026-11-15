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
  name: string;
  position: string | null;
  school: string | null;
  major: string | null;
  bio: string | null;
  photo_url: string | null;
  recorded: boolean;
  contact: Partial<Record<ShareableField, string>>;
  tapped_at: string;
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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");

  let resp: Response;
  try {
    resp = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, errorMessage(0, null));
  }
  if (resp.status === 204) return undefined as T;
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    if (resp.status === 401) tokenStore.set(null); // expired or deleted account
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
  /** Email the signed-in person their summary for this event right now. */
  testEmail: (eventId: number) => request<{ sent_to: string; delivered: boolean }>(`/events/${eventId}/test-email`, { method: "POST" }),
};

export const api: typeof serverApi = PREVIEW ? { ...serverApi, ...previewApi } : serverApi;

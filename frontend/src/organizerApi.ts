/**
 * Client for the organizer console. Every call sends the organizer key
 * (X-Admin-Key), which the backend gets from ADMIN_API_KEY on Render.
 */

import { adminKeyStore, ApiError, request, type EventInfo } from "./api";

export interface Attendee {
  user_id: number;
  name: string;
  email: string | null;
  school: string | null;
  major: string | null;
  photo_url: string | null;
  bracelet_id: string;
  assigned_at: string;
  recording_consent: boolean | null;
  summary_email_opt_in: boolean;
  connections: number;
  email_status: "sent" | "failed" | null;
}

export interface Overview {
  event: EventInfo;
  attendees: number;
  recording_consent: number;
  summary_email_opt_in: number;
  connections: number;
  uploads_received: number;
  emails_sent: number;
  emails_failed: number;
}

export interface SendResult {
  sent: number;
  skipped_already_sent: number;
  skipped_opted_out: number;
  skipped_no_email: number;
  failed: number;
  failures: string[];
}

export interface EventFields {
  name: string;
  location: string | null;
  starts_at: string | null;
}

const admin = <T>(path: string, init: RequestInit = {}) => request<T>(path, init, "admin");
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const organizerApi = {
  /** Check a key and keep it if it works. */
  signIn: async (key: string) => {
    adminKeyStore.set(key.trim());
    try {
      return await admin<{ ok: boolean; email_backend: string }>("/admin/check");
    } catch (err) {
      adminKeyStore.set(null);
      if (err instanceof ApiError && err.status === 401) throw new ApiError(401, "That organizer key doesn't match. Check it and try again.");
      throw err;
    }
  },
  signOut: () => adminKeyStore.set(null),
  signedIn: () => !!adminKeyStore.get(),
  check: () => admin<{ ok: boolean; email_backend: string }>("/admin/check"),

  events: () => request<EventInfo[]>("/events"),
  createEvent: (fields: EventFields) => admin<EventInfo>("/events", json("POST", fields)),
  updateEvent: (id: number, fields: Partial<EventFields>) => admin<EventInfo>(`/events/${id}`, json("PATCH", fields)),
  overview: (id: number) => admin<Overview>(`/events/${id}/overview`),
  attendees: (id: number) => admin<Attendee[]>(`/events/${id}/attendees`),
  assign: (id: number, email: string, braceletId: string) =>
    admin<Attendee>(`/events/${id}/attendees`, json("POST", { email, bracelet_id: braceletId })),
  release: (id: number, userId: number) => admin<void>(`/events/${id}/attendees/${userId}`, { method: "DELETE" }),
  sendSummaries: (id: number, resend: boolean) =>
    admin<SendResult>(`/events/${id}/send-summaries`, json("POST", { resend })),
  testEmail: (to: string) => admin<{ sent: boolean; backend: string }>("/admin/email/test", json("POST", { to })),
};

/** Where attendees open the app: this site's own address plus /e/<id>. */
export function eventLink(eventId: number, braceletId?: string): string {
  const base = new URL(import.meta.env.BASE_URL, window.location.origin).toString().replace(/\/$/, "");
  const id = braceletId?.replace(/[\s:-]/g, "").toUpperCase();
  return `${base}/e/${eventId}${id ? `?b=${encodeURIComponent(id)}` : ""}`;
}

/** The backend stores UTC; SQLite hands it back without an offset. */
export function parseServerDate(value: string | null): Date | null {
  if (!value) return null;
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Date -> the "YYYY-MM-DDTHH:mm" a datetime-local input wants, in local time. */
export function toLocalInput(value: string | null): string {
  const d = parseServerDate(value);
  if (!d) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatWhen(value: string | null): string | null {
  const d = parseServerDate(value);
  if (!d) return null;
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** Organizer console, against a fake fetch. */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adminKeyStore } from "../api";
import { eventLink, parseServerDate } from "../organizerApi";
import Organizer from "../screens/organizer/Organizer";

const EVENT = { id: 3, name: "Viterbi Industry Night", location: "Town & Gown", starts_at: null };
const OVERVIEW = {
  event: EVENT, attendees: 2, recording_consent: 1, summary_email_opt_in: 2, connections: 5,
  uploads_received: 0, emails_sent: 0, emails_failed: 0,
};
const ADA = {
  user_id: 7, name: "Ada Lovelace", email: "ada@usc.edu", school: "Viterbi", major: "CS", photo_url: null,
  bracelet_id: "A4CF0001", assigned_at: "2026-11-20T18:05:00", recording_consent: true,
  summary_email_opt_in: true, connections: 3, email_status: null,
};

type Handler = unknown | ((body: unknown, headers: Headers) => Response | unknown);

function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown; key_header: string | null }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${new URL(url).pathname}`;
    const headers = new Headers(init.headers);
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
    calls.push({ key, body, key_header: headers.get("X-Admin-Key") });
    if (!(key in routes)) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    const r = routes[key];
    const out = typeof r === "function" ? r(body, headers) : r;
    return out instanceof Response ? out : new Response(JSON.stringify(out), { status: 200 });
  }));
  return calls;
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/organizer/*" element={<Organizer />} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("organizer console", () => {
  it("signs in with the organizer key and sends it on every call", async () => {
    const calls = mockApi({
      "GET /admin/check": (_b: unknown, h: Headers) =>
        h.get("X-Admin-Key") === "right"
          ? { ok: true, email_backend: "smtp" }
          : new Response(JSON.stringify({ detail: "Invalid admin key" }), { status: 401 }),
      "GET /events": [EVENT],
    });
    renderAt("/organizer");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Organizer key"), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/doesn't match/)).toBeInTheDocument();
    expect(adminKeyStore.get()).toBeNull();

    await user.clear(screen.getByLabelText("Organizer key"));
    await user.type(screen.getByLabelText("Organizer key"), "right");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("link", { name: /Viterbi Industry Night/ })).toBeInTheDocument();
    expect(adminKeyStore.get()).toBe("right");
    expect(calls.filter((c) => c.key === "GET /admin/check").at(-1)?.key_header).toBe("right");
  });

  it("creates an event and opens it", async () => {
    adminKeyStore.set("k");
    const calls = mockApi({
      "GET /admin/check": { ok: true },
      "GET /events": [],
      "POST /events": (body: unknown) => ({ ...EVENT, ...(body as object) }),
      "GET /events/3/overview": { ...OVERVIEW, attendees: 0 },
      "GET /events/3/attendees": [],
    });
    renderAt("/organizer/new");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Event name"), "Viterbi Industry Night");
    await user.click(screen.getByRole("button", { name: "Create event" }));

    expect(await screen.findByText("No one has checked in yet.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /events")?.body).toEqual({
      name: "Viterbi Industry Night", location: null, starts_at: null,
    });
    expect(screen.getByText(eventLink(3))).toBeInTheDocument();
  });

  it("summarizes the event and links a bracelet at the desk", async () => {
    adminKeyStore.set("k");
    const calls = mockApi({
      "GET /admin/check": { ok: true },
      "GET /events": [EVENT],
      "GET /events/3/overview": OVERVIEW,
      "GET /events/3/attendees": [ADA],
      "POST /events/3/attendees": ADA,
    });
    renderAt("/organizer/events/3");
    expect(await screen.findByText("2 people checked in. 1 agreed to recording. 5 taps so far.")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Attendee email"), "ada@usc.edu");
    await user.type(screen.getByLabelText("Bracelet ID"), "a4:cf:00:01");
    await user.click(screen.getByRole("button", { name: "Link bracelet" }));
    expect(await screen.findByText("Linked bracelet A4CF0001 to Ada Lovelace.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /events/3/attendees")?.body).toEqual({
      email: "ada@usc.edu", bracelet_id: "a4:cf:00:01",
    });
  });

  it("asks before taking a bracelet back", async () => {
    adminKeyStore.set("k");
    const calls = mockApi({
      "GET /admin/check": { ok: true },
      "GET /events": [EVENT],
      "GET /events/3/overview": OVERVIEW,
      "GET /events/3/attendees": [ADA],
      "DELETE /events/3/attendees/7": new Response(null, { status: 204 }),
    });
    renderAt("/organizer/events/3?tab=attendees");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Take back" }));
    expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Take back Ada Lovelace's bracelet" }));
    await waitFor(() => expect(calls.some((c) => c.key === "DELETE /events/3/attendees/7")).toBe(true));
  });

  it("confirms before sending summary emails and reports the result", async () => {
    adminKeyStore.set("k");
    const calls = mockApi({
      "GET /admin/check": { ok: true },
      "GET /events": [EVENT],
      "GET /events/3/overview": OVERVIEW,
      "GET /events/3/attendees": [ADA],
      "POST /events/3/send-summaries": {
        sent: 1, skipped_already_sent: 0, skipped_opted_out: 0, skipped_no_email: 0, failed: 1, failures: ["user 9: bounced"],
      },
    });
    renderAt("/organizer/events/3?tab=after");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Send summary emails" }));
    expect(calls.some((c) => c.key.includes("send-summaries"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Send emails" }));
    expect(await screen.findByText("Sent 1. 1 failed.")).toBeInTheDocument();
    expect(screen.getByText("user 9: bounced")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /events/3/send-summaries")?.body).toEqual({ resend: false });
  });
});

describe("organizer helpers", () => {
  it("builds tap links with a normalized bracelet id", () => {
    expect(eventLink(3, "a4:cf-00 01")).toMatch(/\/e\/3\?b=A4CF0001$/);
    expect(eventLink(3)).toMatch(/\/e\/3$/);
  });

  it("reads server times without an offset as UTC", () => {
    expect(parseServerDate("2026-11-20T18:00:00")?.toISOString()).toBe("2026-11-20T18:00:00.000Z");
    expect(parseServerDate("2026-11-20T18:00:00+00:00")?.toISOString()).toBe("2026-11-20T18:00:00.000Z");
    expect(parseServerDate(null)).toBeNull();
  });
});

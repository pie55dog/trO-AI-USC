/**
 * Frontend tests. The API is mocked with a fake fetch so these run offline;
 * the real backend is covered by backend/tests.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tokenStore, type Connection, type Me } from "../api";
import { wordCount } from "../hooks";
import AuthCallback from "../screens/AuthCallback";
import EventHome, { ConnectionCard, TestEmail } from "../screens/EventHome";
import Preferences from "../screens/Preferences";
import Tutorial from "../screens/Tutorial";
import Welcome, { validate } from "../screens/Welcome";
import { emptyDraft } from "../session";

const me = (over: Partial<Me["preferences"]> = {}, complete = true): Me => ({
  profile: {
    id: 1, name: "Tommy Trojan", email: "t@usc.edu", school: "Viterbi", major: "CS", bio: "one two three four five",
    interests: ["AI & ML"], position: null, linkedin_url: null, company: null, website: null, portfolio_url: null,
    instagram: null, photo_url: null,
  },
  preferences: {
    recording_consent: null, recording_consent_updated_at: null, recommendations_opt_in: null,
    summary_email_opt_in: true, shared_fields: ["email"], ...over,
  },
  onboarding: { complete, missing: complete ? [] : ["recording_consent"] },
});

/** Fake fetch: route "METHOD /path" to a JSON body (or a function of the request body). */
function mockApi(routes: Record<string, unknown | ((body: unknown) => unknown)>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = new URL(url).pathname;
    const key = `${init.method ?? "GET"} ${path}`;
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body;
    calls.push({ key, body });
    if (!(key in routes)) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    const r = routes[key];
    return new Response(JSON.stringify(typeof r === "function" ? r(body) : r), { status: 200 });
  }));
  return calls;
}

function renderAt(path: string, element: React.ReactElement, routePath: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={routePath} element={element} />
        <Route path="*" element={<p>navigated</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("helpers", () => {
  it("counts words", () => {
    expect(wordCount("")).toBe(0);
    expect(wordCount("  Into AI   and hackathons. ")).toBe(4);
  });

  it("validates the profile like the backend's onboarding rules", () => {
    const errors = validate(emptyDraft);
    expect(Object.keys(errors).sort()).toEqual(["email", "interests", "major", "name", "school"]);
    const ok = validate({
      ...emptyDraft, name: "T", email: "t@usc.edu", school: "V", major: "CS",
      bio: "one two three four five", interests: ["AI & ML"],
    });
    expect(ok).toEqual({});
    expect(validate({ ...emptyDraft, bio: "" }).bio).toBeUndefined(); // bio is optional
    expect(validate({ ...emptyDraft, bio: "short" }).bio).toBeUndefined(); // no minimum
    expect(validate({ ...emptyDraft, bio: Array(21).fill("w").join(" ") }).bio).toBeDefined();
  });
});

describe("start of the flow", () => {
  /** Shows where a screen navigated to, so a test can check the path. */
  function renderFlow(path: string) {
    const Where = () => <p data-testid="where">{window.location.pathname}</p>;
    render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/e/:eventId" element={<EventHome />} />
          <Route path="/e/:eventId/tutorial" element={<Tutorial />} />
          <Route path="/e/:eventId/welcome" element={<p>welcome screen</p>} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("opens how it works for someone new, then goes to step 1", async () => {
    mockApi({ "GET /events/1": { id: 1, name: "Demo night" } });
    renderFlow("/e/1?b=TEST01");
    expect(await screen.findByText(/how it works/i)).toBeTruthy();
    expect(screen.getByText("This is trO")).toBeTruthy();
    // Five pages: walk through them to the last one.
    await userEvent.click(screen.getByRole("button", { name: /show me how/i }));
    expect(screen.getByText("When you meet someone, tap bracelets")).toBeTruthy();
    for (let i = 0; i < 3; i++) await userEvent.click(screen.getByRole("button", { name: /^next/i }));
    expect(screen.getByText("Before you go")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /got it/i }));
    expect(await screen.findByText("welcome screen")).toBeTruthy();
  });

  it("lets people skip how it works", async () => {
    mockApi({ "GET /events/1": { id: 1, name: "Demo night" } });
    renderFlow("/e/1?b=TEST01");
    await userEvent.click(await screen.findByRole("button", { name: /skip/i }));
    expect(await screen.findByText("welcome screen")).toBeTruthy();
  });

  it("sends someone part way through setup to step 1, not back to how it works", async () => {
    tokenStore.set("t");
    mockApi({ "GET /events/1": { id: 1, name: "Demo night" }, "GET /users/me": me({}, false) });
    renderFlow("/e/1");
    expect(await screen.findByText("welcome screen")).toBeTruthy();
  });
});

describe("Welcome (step 1)", () => {
  it("shows the bracelet from the tap link and creates an account on Continue", async () => {
    const calls = mockApi({
      "GET /events/1": { id: 1, name: "Industry Night", location: null, starts_at: null },
      "POST /users": { token: "tok", me: me() },
      "PATCH /users/me": me(),
    });
    renderAt("/e/1/welcome?b=a4:cf:00:42", <Welcome />, "/e/:eventId/welcome");

    expect(await screen.findByText("Bracelet A4CF0042 linked")).toBeInTheDocument();
    expect(await screen.findByText(/Industry Night\./)).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getByText("Add your name.")).toBeInTheDocument(); // nothing sent yet
    expect(calls.some((c) => c.key === "POST /users")).toBe(false);

    await user.type(screen.getByLabelText("Send my summary to"), "t@usc.edu");
    await user.type(screen.getByLabelText("Name"), "Tommy Trojan");
    await user.type(screen.getByLabelText("School"), "Viterbi");
    await user.type(screen.getByLabelText("Major"), "CS");
    await user.type(screen.getByLabelText(/Bio/), "Junior building tools for student orgs.");
    await user.click(screen.getByRole("button", { name: "AI & ML" }));
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await screen.findByText("navigated");
    expect(tokenStore.get()).toBe("tok");
    const patch = calls.find((c) => c.key === "PATCH /users/me")!.body as Record<string, unknown>;
    expect(patch).toMatchObject({ name: "Tommy Trojan", interests: ["AI & ML"], position: null });
  });
});

describe("Preferences (step 2)", () => {
  it("needs both answers, then saves and links the bracelet", async () => {
    tokenStore.set("tok");
    localStorage.setItem("tro.bracelet.1", "A4CF0042");
    const calls = mockApi({
      "GET /events/1": { id: 1, name: "Industry Night", location: null, starts_at: null },
      "GET /users/me": me(),
      "PUT /users/me/preferences": me({ recording_consent: true, recommendations_opt_in: false }),
      "POST /events/1/bracelet": { event_id: 1, bracelet_id: "A4CF0042", assigned_at: "" },
    });
    renderAt("/e/1/preferences", <Preferences />, "/e/:eventId/preferences");

    const finish = await screen.findByRole("button", { name: /finish setup/i });
    expect(finish).toBeDisabled();
    // Nothing is pre-selected: consent must be an explicit choice.
    expect(screen.getAllByRole("radio").every((r) => r.getAttribute("aria-checked") === "false")).toBe(true);

    const user = userEvent.setup();
    const [recording, recs] = screen.getAllByRole("radiogroup");
    await user.click(recording.querySelector("[aria-checked]:nth-child(2)")!); // Yes
    expect(finish).toBeDisabled();
    await user.click(recs.querySelector("[aria-checked]:nth-child(1)")!); // No
    expect(finish).toBeEnabled();
    await user.click(finish);

    await screen.findByText("navigated");
    expect(calls.find((c) => c.key === "PUT /users/me/preferences")!.body).toEqual({
      recording_consent: true,
      recommendations_opt_in: false,
    });
    expect(calls.find((c) => c.key === "POST /events/1/bracelet")!.body).toEqual({ bracelet_id: "A4CF0042" });
  });
});

describe("Dashboard connection card", () => {
  const person: Connection = {
    user_id: 2, name: "Priya Shah", position: "Product Manager at Snap", school: null, major: null,
    bio: "Hosts a monthly coffee chat.", photo_url: null, recorded: false,
    contact: { email: "priya@usc.edu" }, tapped_at: "",
  };

  it("shows only shared contact options and the recording status", () => {
    render(<ConnectionCard person={person} />);
    expect(screen.getByText("Contact only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy email/i })).toBeInTheDocument();
    expect(screen.queryByText("LinkedIn")).not.toBeInTheDocument();
    expect(screen.queryByText(/match/)).not.toBeInTheDocument(); // no fake match %
  });

  it("marks recorded conversations and links out", () => {
    render(<ConnectionCard person={{ ...person, recorded: true, contact: { linkedin_url: "https://linkedin.com/in/p" } }} />);
    expect(screen.getByText("Recorded")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /linkedin/i })).toHaveAttribute("href", "https://linkedin.com/in/p");
  });
});

describe("LinkedIn callback", () => {
  it("stores the token and returns to the profile", async () => {
    localStorage.setItem("tro.returnTo", "/e/1/welcome");
    window.history.replaceState(null, "", "/auth/callback#token=abc&new_user=1");
    renderAt("/auth/callback", <AuthCallback />, "/auth/callback");
    await screen.findByText("navigated");
    expect(tokenStore.get()).toBe("abc");
    expect(window.location.hash).toBe("");
  });

  it("explains a cancelled sign-in", async () => {
    window.history.replaceState(null, "", "/auth/callback#error=cancelled");
    renderAt("/auth/callback", <AuthCallback />, "/auth/callback");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/cancelled/));
    expect(tokenStore.get()).toBeNull();
  });
});

describe("bracelet already taken", () => {
  it("still finishes setup and forgets the bracelet", async () => {
    tokenStore.set("tok");
    localStorage.setItem("tro.bracelet.1", "A4CF0042");
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
      const key = `${init.method ?? "GET"} ${new URL(url).pathname}`;
      if (key === "POST /events/1/bracelet")
        return new Response(JSON.stringify({ detail: "this bracelet is already assigned to someone else" }), { status: 409 });
      if (key === "GET /users/me") return new Response(JSON.stringify(me()));
      if (key === "PUT /users/me/preferences") return new Response(JSON.stringify(me({ recording_consent: false, recommendations_opt_in: false })));
      return new Response("{}", { status: 404 });
    }));
    renderAt("/e/1/preferences", <Preferences />, "/e/:eventId/preferences");
    const user = userEvent.setup();
    const finish = await screen.findByRole("button", { name: /finish setup/i });
    for (const group of screen.getAllByRole("radiogroup")) await user.click(group.querySelector("[aria-checked]")!);
    await user.click(finish);
    await screen.findByText("navigated");
    expect(localStorage.getItem("tro.bracelet.1")).toBeNull();
  });
});

describe("test email button", () => {
  it("sends the summary to the signed-in person and says where it went", async () => {
    tokenStore.set("t");
    const calls = mockApi({ "POST /events/3/test-email": { sent_to: "t@usc.edu", delivered: true } });
    render(<TestEmail eventId={3} email="t@usc.edu" />);
    await userEvent.click(screen.getByRole("button", { name: /send me a test email/i }));
    expect(await screen.findByRole("status")).toHaveTextContent("Sent to t@usc.edu");
    expect(calls.map((c) => c.key)).toEqual(["POST /events/3/test-email"]);
  });

  it("shows the server's reason when sending fails", async () => {
    tokenStore.set("t");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "SMTP is not configured" }), { status: 503 })));
    render(<TestEmail eventId={3} email="t@usc.edu" />);
    await userEvent.click(screen.getByRole("button", { name: /send me a test email/i }));
    expect(await screen.findByText("SMTP is not configured")).toBeInTheDocument();
  });
});


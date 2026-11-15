import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { tokenStore } from "../api";
import { SampleStore } from "../phoneMic/audio";
import { PhoneMicController } from "../phoneMic/controller";
import PhoneMic from "../screens/PhoneMic";

afterEach(() => {
  cleanup();
  tokenStore.set(null);
  vi.unstubAllGlobals();
});

it("turns the mic on, waits for a tap, and records it", async () => {
  tokenStore.set("t");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 404 })));
  const source = { store: new SampleStore(), level: 0, start: vi.fn(async () => undefined), stop: vi.fn() };
  let controller: PhoneMicController | null = null;
  const make = (eventId: number) =>
    (controller = new PhoneMicController({
      source,
      eventId,
      connections: async () => [],
      upload: async () => ({}),
      setInterval: () => 0,
      clearInterval: () => undefined,
    }));

  render(
    <MemoryRouter initialEntries={["/e/3/mic"]}>
      <Routes>
        <Route path="/e/:eventId/mic" element={<PhoneMic makeController={make} />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("Mic is off")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /turn on phone mic/i }));
  expect(await screen.findByText("Listening for your next tap")).toBeInTheDocument();
  expect(source.start).toHaveBeenCalled();

  const tap = {
    user_id: 9, connection_id: 4, name: "Bob Li", position: null, school: null, major: null, bio: null, photo_url: null,
    recorded: false, both_consented: true, contact: {}, tapped_at: new Date().toISOString(),
  };
  controller!.handleConnections([tap]);
  expect(await screen.findByText("Recording with Bob Li")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /end conversation/i })).toBeInTheDocument();
});

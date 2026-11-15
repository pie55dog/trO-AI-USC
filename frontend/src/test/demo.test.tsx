import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { tokenStore } from "../api";
import Demo from "../screens/Demo";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

describe("demo hub", () => {
  it("links every screen of the flow", () => {
    render(<MemoryRouter><Demo /></MemoryRouter>);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/e/1/tutorial", "/e/1/welcome", "/e/1/preferences", "/e/1", "/demo/notes", "/organizer"]);
  });

  it("start over signs out, clears saved data and opens step 1", async () => {
    tokenStore.set("preview");
    localStorage.setItem("tro.preview", "{}");
    localStorage.setItem("tro.profileDraft", "{}");
    render(
      <MemoryRouter initialEntries={["/demo"]}>
        <Routes>
          <Route path="/demo" element={<Demo />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /start over/i }));
    expect(screen.getByTestId("where").textContent).toBe("/e/1/tutorial");
    expect(tokenStore.get()).toBeNull();
    expect(localStorage.getItem("tro.preview")).toBeNull();
    expect(localStorage.getItem("tro.profileDraft")).toBeNull();
  });
});

describe("home without a bracelet", () => {
  it("offers to try the sign-up without a bracelet", async () => {
    const { default: App } = await import("../App");
    render(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);
    expect(screen.getByRole("link", { name: /proceed without a bracelet/i })).toHaveAttribute("href", "/e/1/tutorial");
  });
});

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { Connection } from "../api";
import { SAMPLE_NOTES } from "../sampleNotes";
import { notesCaption } from "../screens/EventHome";
import { NotesView } from "../screens/PersonNotes";

afterEach(cleanup);

const base = SAMPLE_NOTES.person;

describe("connection card notes line", () => {
  it("matches the Figma wording", () => {
    const p: Connection = { ...base, notes: { conversation: "ready", voice_notes: 1, follow_ups: 1 } };
    expect(notesCaption(p)).toBe("AI summary · 1 voice note · follow-up idea");
  });
  it("says when notes are still being written", () => {
    expect(notesCaption({ ...base, notes: { conversation: "processing", voice_notes: 0, follow_ups: 0 } })).toBe("Writing your notes…");
  });
  it("contact-only people still collect voice notes", () => {
    expect(notesCaption({ ...base, recorded: false, notes: { conversation: "not_recorded", voice_notes: 2, follow_ups: 0 } })).toBe("2 voice notes");
  });
});

describe("notes screen", () => {
  it("shows the sample conversation, labelled as a sample", async () => {
    render(<MemoryRouter><NotesView data={SAMPLE_NOTES} back={{ to: "/demo", label: "Back" }} sample /></MemoryRouter>);
    expect(screen.getByText("Sample conversation")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Jordan." })).toBeInTheDocument();
    expect(screen.getByText(/send you the link to the summer internship/)).toBeInTheDocument();
    // Transcript is collapsed until asked for, then labels each line by speaker.
    expect(screen.queryByText(/I'm a junior in computer science/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /show transcript/i }));
    expect(screen.getByText(/I'm a junior in computer science/)).toBeInTheDocument();
    expect(screen.getAllByText("You").length).toBeGreaterThan(0);
    expect(screen.getByText(/measured from both bracelets/)).toBeInTheDocument();
  });

  it("explains a contact-only connection instead of inventing notes", () => {
    const data = { ...SAMPLE_NOTES, conversation: null, conversation_status: "not_recorded" as const, voice_notes: [] };
    render(<MemoryRouter><NotesView data={data} back={{ to: "/e/1", label: "Back" }} /></MemoryRouter>);
    expect(screen.getByText("Contact only", { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByText("Promises")).toBeNull();
    expect(screen.queryByText("Sample conversation")).toBeNull();
  });
});

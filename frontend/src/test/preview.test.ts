import { afterEach, describe, expect, it } from "vitest";
import { ApiError, tokenStore } from "../api";
import { previewApi } from "../preview";

afterEach(() => localStorage.clear());

describe("preview mode (no backend)", () => {
  it("runs the onboarding flow on the phone with the backend's rules", async () => {
    const { token, me } = await previewApi.signUp("Tommy Trojan", "tommy@usc.edu");
    tokenStore.set(token);
    expect(me.onboarding.missing).toEqual(["school", "major", "bio", "interests", "recording_consent", "recommendations_opt_in"]);

    // Can't take a bracelet before onboarding is complete.
    await expect(previewApi.claimBracelet(1, "ABC123")).rejects.toMatchObject({ status: 409 });

    await previewApi.updateProfile({ school: "USC", major: "CS", bio: "Hi", interests: ["AI"] });
    const done = await previewApi.savePreferences({ recording_consent: true, recommendations_opt_in: false });
    expect(done.onboarding.complete).toBe(true);
    expect(done.preferences.recording_consent_updated_at).not.toBeNull();

    await previewApi.claimBracelet(1, "ABC123");
    expect((await previewApi.myBracelet(1)).bracelet_id).toBe("ABC123");
    // Never invents connections or events.
    expect(await previewApi.connections(1)).toEqual([]);
    await expect(previewApi.event(1)).rejects.toBeInstanceOf(ApiError);
  });

  it("treats a missing token as signed out", async () => {
    await previewApi.signUp("A", "a@usc.edu");
    await expect(previewApi.me()).rejects.toMatchObject({ status: 401 });
  });
});

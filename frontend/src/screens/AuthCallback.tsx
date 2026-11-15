/**
 * Where LinkedIn sign-in lands: /auth/callback#token=...&new_user=1
 * (or #error=cancelled|state|linkedin). Saves the token and goes back to
 * the screen that started sign-in.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { tokenStore } from "../api";
import { ErrorNote, Loading, PrimaryButton, Screen } from "../components/ui";
import { lastEventStore, returnStore } from "../session";

const MESSAGES: Record<string, string> = {
  cancelled: "LinkedIn sign-in was cancelled. You can fill in your profile yourself instead.",
  state: "That sign-in link expired. Please try again.",
  linkedin: "LinkedIn didn’t respond. Please try again, or fill in your profile yourself.",
};

export default function AuthCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const back = returnStore.get() ?? (lastEventStore.get() ? `/e/${lastEventStore.get()}/welcome` : "/");

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    // Drop the token from the address bar right away.
    window.history.replaceState(null, "", window.location.pathname);
    const token = params.get("token");
    if (token) {
      tokenStore.set(token);
      returnStore.set(null);
      navigate(back, { replace: true });
    } else {
      setError(MESSAGES[params.get("error") ?? ""] ?? MESSAGES.linkedin);
    }
  }, [navigate, back]);

  if (!error) return <Screen><Loading label="Signing you in" /></Screen>;
  return (
    <Screen className="justify-center gap-4">
      <ErrorNote>{error}</ErrorNote>
      <PrimaryButton onClick={() => navigate(back, { replace: true })}>Back to my profile</PrimaryButton>
    </Screen>
  );
}

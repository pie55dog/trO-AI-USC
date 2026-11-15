/**
 * Routes. A bracelet tap opens /e/<eventId>?b=<braceletId>.
 *
 *   /e/:eventId              event dashboard (sends new people to /welcome)
 *   /e/:eventId/welcome      step 1: email + profile
 *   /e/:eventId/preferences  step 2: recording consent + recommendations
 *   /e/:eventId/tutorial     how trO works
 *   /demo                    demo hub linking every screen (home page on preview builds)
 *   /auth/callback           LinkedIn sign-in returns here
 */

import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { PREVIEW } from "./api";
import { Screen } from "./components/ui";
import AuthCallback from "./screens/AuthCallback";
import Demo from "./screens/Demo";
import EventHome from "./screens/EventHome";
import Preferences from "./screens/Preferences";
import Tutorial from "./screens/Tutorial";
import Welcome from "./screens/Welcome";
import { lastEventStore } from "./session";

function Home() {
  // A preview build has no bracelets to tap, so its front page is the demo hub.
  if (PREVIEW) return <Demo />;
  const last = lastEventStore.get();
  if (last) return <Navigate to={`/e/${last}`} replace />;
  return (
    <Screen className="justify-center gap-2 text-center">
      <h1 className="text-title font-semibold">Tap your bracelet to start</h1>
      <p className="text-body text-ink-muted">Hold your trO bracelet to your phone to open your event.</p>
    </Screen>
  );
}

/**
 * Remount a screen when the event or tap link changes, so per-screen state
 * (like the bracelet id read from `?b=`) never carries over between events.
 */
function PerEvent({ children }: { children: ReactNode }) {
  const { eventId } = useParams();
  const { search } = useLocation();
  return <div key={`${eventId}${search}`} className="contents">{children}</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/demo" element={<Demo />} />
      <Route path="/e/:eventId" element={<PerEvent><EventHome /></PerEvent>} />
      <Route path="/e/:eventId/welcome" element={<PerEvent><Welcome /></PerEvent>} />
      <Route path="/e/:eventId/preferences" element={<PerEvent><Preferences /></PerEvent>} />
      <Route path="/e/:eventId/tutorial" element={<PerEvent><Tutorial /></PerEvent>} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

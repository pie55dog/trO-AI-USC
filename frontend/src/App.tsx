/**
 * Routes. A bracelet tap opens /e/<eventId>?b=<braceletId>.
 *
 *   /e/:eventId              event dashboard (sends new people to /welcome)
 *   /e/:eventId/welcome      step 1: email + profile
 *   /e/:eventId/preferences  step 2: recording consent + recommendations
 *   /e/:eventId/tutorial     how trO works
 *   /auth/callback           LinkedIn sign-in returns here
 */

import { Navigate, Route, Routes } from "react-router-dom";
import { Screen } from "./components/ui";
import AuthCallback from "./screens/AuthCallback";
import EventHome from "./screens/EventHome";
import Preferences from "./screens/Preferences";
import Tutorial from "./screens/Tutorial";
import Welcome from "./screens/Welcome";
import { lastEventStore } from "./session";

function Home() {
  const last = lastEventStore.get();
  if (last) return <Navigate to={`/e/${last}`} replace />;
  return (
    <Screen className="justify-center gap-2 text-center">
      <h1 className="text-title font-semibold">Tap your bracelet to start</h1>
      <p className="text-body text-ink-muted">Hold your trO bracelet to your phone to open your event.</p>
    </Screen>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/e/:eventId" element={<EventHome />} />
      <Route path="/e/:eventId/welcome" element={<Welcome />} />
      <Route path="/e/:eventId/preferences" element={<Preferences />} />
      <Route path="/e/:eventId/tutorial" element={<Tutorial />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

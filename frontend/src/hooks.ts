import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, type EventInfo } from "./api";
import { braceletStore, lastEventStore } from "./session";

/**
 * The event this screen belongs to, from the URL (/e/:eventId).
 *
 * Tapping a bracelet opens a link like /e/3?b=A4CF129B001E. We remember the
 * bracelet id per event so it survives the LinkedIn round trip and later
 * visits without the query string.
 */
export function useEventContext() {
  const { eventId: raw } = useParams();
  const [search] = useSearchParams();
  const eventId = Number(raw);
  const valid = Number.isInteger(eventId) && eventId > 0;

  // Same normalization as the backend: "a4:cf:00:42" -> "A4CF0042".
  const fromUrl = search.get("b")?.replace(/[\s:-]/g, "").toUpperCase();
  if (valid && fromUrl) braceletStore.set(eventId, fromUrl);
  if (valid) lastEventStore.set(eventId);

  const [event, setEvent] = useState<EventInfo | null>(null);
  useEffect(() => {
    if (!valid) return;
    let alive = true;
    // The event name is nice-to-have; the screen still works with "event".
    api.event(eventId).then((e) => alive && setEvent(e), () => undefined);
    return () => {
      alive = false;
    };
  }, [eventId, valid]);

  return {
    eventId: valid ? eventId : null,
    braceletId: valid ? braceletStore.get(eventId) : null,
    // Falls back to the Figma placeholder text until the name loads.
    eventName: event?.name ?? "event",
  };
}

/** Count words the way people do: runs of non-space characters. */
export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

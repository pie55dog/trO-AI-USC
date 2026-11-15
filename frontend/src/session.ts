/**
 * Small pieces of state that must survive a page reload, because LinkedIn
 * sign-in leaves the app and comes back:
 *
 *  - which bracelet this phone tapped (from the `?b=` in the tap link),
 *  - where to return after LinkedIn,
 *  - the half-filled profile form.
 */

import { storageGet, storageSet } from "./api";

const braceletKey = (eventId: number) => `tro.bracelet.${eventId}`;
const RETURN_KEY = "tro.returnTo";
const DRAFT_KEY = "tro.profileDraft";
const LAST_EVENT_KEY = "tro.lastEvent";

export const braceletStore = {
  get: (eventId: number) => storageGet(braceletKey(eventId)),
  set: (eventId: number, id: string) => storageSet(braceletKey(eventId), id),
  clear: (eventId: number) => storageSet(braceletKey(eventId), null),
};

export const lastEventStore = {
  get: () => {
    const v = Number(storageGet(LAST_EVENT_KEY));
    return Number.isInteger(v) && v > 0 ? v : null;
  },
  set: (eventId: number) => storageSet(LAST_EVENT_KEY, String(eventId)),
};

export const returnStore = {
  get: () => storageGet(RETURN_KEY),
  set: (path: string | null) => storageSet(RETURN_KEY, path),
};

export interface ProfileDraft {
  name: string;
  email: string;
  school: string;
  major: string;
  bio: string;
  position: string;
  interests: string[];
  linkedin_url: string;
  portfolio_url: string;
  website: string;
  instagram: string;
}

export const emptyDraft: ProfileDraft = {
  name: "",
  email: "",
  school: "",
  major: "",
  bio: "",
  position: "",
  interests: [],
  linkedin_url: "",
  portfolio_url: "",
  website: "",
  instagram: "",
};

export const draftStore = {
  get: (): ProfileDraft | null => {
    try {
      const raw = storageGet(DRAFT_KEY);
      return raw ? { ...emptyDraft, ...JSON.parse(raw) } : null;
    } catch {
      return null;
    }
  },
  set: (draft: ProfileDraft | null) => storageSet(DRAFT_KEY, draft ? JSON.stringify(draft) : null),
};

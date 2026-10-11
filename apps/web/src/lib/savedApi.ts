import { api, type ContentSummary } from "./api";
import type { PersonaKey } from "./personas";

/** Saved articles (Design pass A6): library items only, never bare web links. */
const q = (persona: PersonaKey | null) => (persona ? `?persona=${persona}` : "");

export const savedApi = {
  list: (persona: PersonaKey | null, signal?: AbortSignal) =>
    api.raw.get<ContentSummary[]>(`/v1/me/saved${q(persona)}`, signal),
  ids: (persona: PersonaKey | null, signal?: AbortSignal) => api.raw.get<string[]>(`/v1/me/saved/ids${q(persona)}`, signal),
  save: (id: string, persona: PersonaKey | null) =>
    api.raw.send<null>("PUT", `/v1/me/saved/${encodeURIComponent(id)}${q(persona)}`, undefined),
  unsave: (id: string, persona: PersonaKey | null) =>
    api.raw.send<null>("DELETE", `/v1/me/saved/${encodeURIComponent(id)}${q(persona)}`, undefined),
};

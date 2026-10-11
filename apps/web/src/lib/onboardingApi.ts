import { api, type RecFormat } from "./api";
import type { Domain } from "./taxonomy";

/** 2-screen onboarding (decisions 41, 42): free text → concepts and topics, then live results. */

export interface ResolvedConcept {
  id: string;
  label: string;
  domain: Domain;
}

export interface ResolvedTopic {
  phrase_index: number;
  phrase: string;
  topic: Domain;
  via: "alias" | "words" | "embedding";
}

export interface ResolveResult {
  concepts: ResolvedConcept[];
  topics: ResolvedTopic[];
  unrecognised: string[];
}

export interface KnowTerm {
  concept_id: string;
  label: string;
  known: boolean | null;
}

export interface DiscoverItem {
  id: string;
  kind: "web" | "library";
  content_id: string | null;
  topic: Domain;
  topic_label: string;
  format: RecFormat;
  title: string;
  url: string;
  source: string;
  snippet: string;
  thumbnail: string | null;
  duration_or_read_time: number | null;
  published_at: string | null;
  know: KnowTerm | null;
  liked: boolean | null;
}

export interface DiscoverResult {
  items: DiscoverItem[];
  pending: boolean;
}

export const onboardingApi = {
  /** The text goes in this one request body and nowhere else (never stored on the client). */
  resolve: (text: string) => api.raw.send<ResolveResult>("POST", "/v1/onboarding/resolve", { text }),
  discover: (topics: Domain[], concepts: string[], signal?: AbortSignal) =>
    api.raw.send<DiscoverResult>("POST", "/v1/onboarding/discover", { topics, concepts }, signal),
  pick: (item_id: string, liked: boolean) =>
    api.raw.send<{ saved: boolean }>("POST", "/v1/onboarding/pick", { item_id, liked }),
  know: (concept_id: string, known: boolean) =>
    api.raw.send<{ saved: boolean }>("POST", "/v1/onboarding/know", { concept_id, known }),
  finish: () => api.raw.send<{ done: boolean }>("POST", "/v1/onboarding/finish", {}),
};

import { api } from "./api";
import type { Country } from "./country";
import type { PersonaKey } from "./personas";

/** For you feed (M7.5 §A). */
export type FeedFormat = "article" | "video" | "podcast";

export interface FeedItem {
  id: string;
  topic: string;
  topic_label: string;
  format: FeedFormat;
  title: string;
  url: string;
  source: string;
  snippet: string;
  thumbnail: string | null;
  duration_or_read_time: number | null;
  published_at: string | null;
  new_concepts: string[];
  goal: string | null;
  why: string;
  score: number;
  /** Opens in Gloss (articles; videos within the media caps). Older APIs omit it: articles only. */
  open_here?: boolean;
}

export interface FeedResponse {
  topics: string[];
  items: FeedItem[];
  pending: boolean;
  snapshot: boolean;
  prepared_at: string | null;
  country?: Country | null; // decision 50: the signed-in reader's choice; null = not set
}

export const feedApi = {
  feed: (persona: PersonaKey | null, signal?: AbortSignal) =>
    api.raw.get<FeedResponse>(`/v1/feed${persona ? `?persona=${persona}` : ""}`, signal),
};

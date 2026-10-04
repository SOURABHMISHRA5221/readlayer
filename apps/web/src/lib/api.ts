import type { CardAnnotation } from "@readlayer/annotator";

import type { Density, PersonaKey } from "./personas";

export interface ContentSummary {
  id: string;
  title: string;
  site: string;
  word_count: number;
  description: string | null;
  author: string | null;
  published: string | null;
  image: string | null;
  domain: string | null;
  concepts_new: number;
}

export interface ContentDetail {
  id: string;
  title: string;
  site: string;
  url: string;
  word_count: number;
  description: string | null;
  author: string | null;
  published: string | null;
  image: string | null;
  domain: string | null;
  paragraphs: { id: string; text: string }[];
}

export interface AnnotationsResponse {
  content_id: string;
  persona: PersonaKey;
  density: Density;
  count: number;
  annotations: CardAnnotation[];
}

export type RecFormat = "article" | "video" | "podcast";
export type RecEventType = "rec_shown" | "rec_clicked" | "rec_dismissed" | "rec_completed";

export interface RecItem {
  id: string;
  kind: "library" | "web";
  relation: "same_story" | "primer" | "deeper" | "angle" | "explainer";
  relation_label: string;
  format: RecFormat;
  title: string;
  url: string;
  content_id: string | null;
  source: string;
  duration_or_read_time: number | null;
  snippet: string;
  thumbnail: string | null;
  published_at: string | null;
  why: string;
  triggers: { id: string; label: string }[];
  score: number;
}

export interface RecsResponse {
  content_id: string;
  persona: PersonaKey;
  prefer: RecFormat | null;
  items: RecItem[];
  pending: boolean;
  web_formats: RecFormat[];
}

export type ApiErrorKind = "not_found" | "unauthorized" | "server" | "offline";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
    readonly detail?: string,
  ) {
    super(detail ?? `api ${kind}${status ? ` ${status}` : ""}`);
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError("offline", null);
  }
  if (!res.ok) {
    const kind = res.status === 404 ? "not_found" : res.status === 401 ? "unauthorized" : "server";
    throw new ApiError(kind, res.status);
  }
  return (await res.json()) as T;
}

/** POST with a JSON body; on failure surfaces the API's own message when it sent one. */
async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      signal,
      keepalive: true,
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError("offline", null);
  }
  if (!res.ok) {
    const data = (await res.json().catch(() => null)) as { message?: string } | null;
    const kind = res.status === 404 ? "not_found" : res.status === 401 ? "unauthorized" : "server";
    throw new ApiError(kind, res.status, data?.message);
  }
  return (await res.json()) as T;
}

export function errorKind(error: unknown): ApiErrorKind {
  return error instanceof ApiError ? error.kind : "offline";
}

export const api = {
  library: (q: string, persona: PersonaKey, density: Density, signal?: AbortSignal) =>
    get<ContentSummary[]>(
      `/v1/content?q=${encodeURIComponent(q)}&persona=${persona}&density=${density}`,
      signal,
    ),
  content: (id: string, signal?: AbortSignal) =>
    get<ContentDetail>(`/v1/content/${encodeURIComponent(id)}`, signal),
  recommendations: (id: string, persona: PersonaKey, prefer: RecFormat | null, signal?: AbortSignal) =>
    get<RecsResponse>(
      `/v1/content/${encodeURIComponent(id)}/recommendations?persona=${persona}${prefer ? `&prefer=${prefer}` : ""}`,
      signal,
    ),
  recEvents: (persona: PersonaKey, events: { id: string; type: RecEventType; item_id: string }[]) =>
    post<{ applied: number; ignored: number }>("/v1/recs/events", { persona, events }),
  openWeb: (url: string, signal?: AbortSignal) =>
    post<{ content_id: string; new: boolean }>("/v1/recs/open", { url }, signal),
  annotations: (id: string, persona: PersonaKey, density: Density, debug: boolean, signal?: AbortSignal) =>
    get<AnnotationsResponse>(
      `/v1/content/${encodeURIComponent(id)}/annotations?persona=${persona}&density=${density}${debug ? "&debug=1" : ""}`,
      signal,
    ),
};

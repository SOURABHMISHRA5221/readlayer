import type { Annotation, CardAnnotation } from "@readlayer/annotator";

import { idToken } from "./auth";
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
  persona: PersonaKey | null;
  density: Density;
  count: number;
  /** Span annotations only, ranked. */
  annotations: CardAnnotation[];
  /** Paragraph markers, the pre-read path and the "Know this?" prompt: shown from M6. */
  extras: { id: string; kind: Exclude<Annotation["kind"], "span"> }[];
}

type RawAnnotations = Omit<AnnotationsResponse, "annotations" | "extras"> & {
  annotations: (CardAnnotation | AnnotationsResponse["extras"][number])[];
};

function splitAnnotations(raw: RawAnnotations): AnnotationsResponse {
  const spans: CardAnnotation[] = [];
  const extras: AnnotationsResponse["extras"] = [];
  for (const a of raw.annotations) {
    if (a.kind === "span") spans.push(a as CardAnnotation);
    else extras.push(a as AnnotationsResponse["extras"][number]);
  }
  return { ...raw, annotations: spans, extras };
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
  persona: PersonaKey | null;
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

export type ReaderEventType = "explain_opened" | "knew_this" | "explain_helpful";

export interface ReaderEvent {
  id: string;
  type: ReaderEventType;
  at: string;
  concept_id: string | null;
  content_id: string | null;
}

/** The API's origin in production (Cloud Run); empty locally, where Vite proxies /v1. */
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").replace(/\/$/, "");

function kindOf(status: number): ApiErrorKind {
  return status === 404 ? "not_found" : status === 401 ? "unauthorized" : "server";
}

/**
 * Every call carries the Firebase ID token. A 401 retries once with a force-refreshed token
 * (the cached one may have just expired); a second 401 means the session is gone.
 */
async function request(path: string, init: RequestInit, signal?: AbortSignal): Promise<Response> {
  const send = async (force: boolean) => {
    const token = await idToken(force);
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(API_BASE + path, { ...init, headers, signal });
  };
  try {
    const res = await send(false);
    return res.status === 401 ? await send(true) : res;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError("offline", null);
  }
}

async function failure(res: Response): Promise<ApiError> {
  const data = (await res.json().catch(() => null)) as { message?: string } | null;
  return new ApiError(kindOf(res.status), res.status, data?.message);
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await request(path, { method: "GET" }, signal);
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

/** JSON body; on failure surfaces the API's own message when it sent one. */
async function send<T>(method: string, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await request(
    path,
    { method, keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    signal,
  );
  if (!res.ok) throw await failure(res);
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown, signal?: AbortSignal) => send<T>("POST", path, body, signal);

export function errorKind(error: unknown): ApiErrorKind {
  return error instanceof ApiError ? error.kind : "offline";
}

/** Demo readers carry a persona; signed-in readers are themselves (no persona param). */
const personaParam = (persona: PersonaKey | null) => (persona ? `&persona=${persona}` : "");

export const api = {
  library: (q: string, persona: PersonaKey | null, density: Density, signal?: AbortSignal) =>
    get<ContentSummary[]>(
      `/v1/content?q=${encodeURIComponent(q)}&density=${density}${personaParam(persona)}`,
      signal,
    ),
  content: (id: string, signal?: AbortSignal) =>
    get<ContentDetail>(`/v1/content/${encodeURIComponent(id)}`, signal),
  recommendations: (id: string, persona: PersonaKey | null, prefer: RecFormat | null, signal?: AbortSignal) =>
    get<RecsResponse>(
      `/v1/content/${encodeURIComponent(id)}/recommendations?${prefer ? `prefer=${prefer}` : ""}${personaParam(persona)}`,
      signal,
    ),
  recEvents: (persona: PersonaKey | null, events: { id: string; type: RecEventType; item_id: string }[]) =>
    post<{ applied: number; ignored: number }>("/v1/recs/events", { persona, events }),
  openWeb: (url: string, signal?: AbortSignal) =>
    post<{ content_id: string; new: boolean }>("/v1/recs/open", { url }, signal),
  annotations: (id: string, persona: PersonaKey | null, density: Density, debug: boolean, signal?: AbortSignal) =>
    get<RawAnnotations>(
      `/v1/content/${encodeURIComponent(id)}/annotations?density=${density}${personaParam(persona)}${debug ? "&debug=1" : ""}`,
      signal,
    ).then(splitAnnotations),
  events: (persona: PersonaKey | null, events: ReaderEvent[]) =>
    post<{ applied: boolean; events_applied: number; events_ignored: number }>("/v1/events", { persona, events }),
  exportMe: async (): Promise<Blob> => {
    const res = await request("/v1/me/export", { method: "GET" });
    if (!res.ok) throw await failure(res);
    return res.blob();
  },
  deleteMe: async (): Promise<void> => {
    const res = await request("/v1/me", { method: "DELETE" });
    if (!res.ok && res.status !== 204) throw await failure(res);
  },
};

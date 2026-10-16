import type {
  CardAnnotation,
  ParagraphMarker,
  PrereadAnnotation,
  PromptAnnotation,
} from "@readlayer/annotator";

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
  /** Library rows badge videos and podcasts (media plan §G). Older APIs omit it: article. */
  format?: RecFormat;
}

/** The recording a transcript was made from (DESIGN §21); the reader plays it from here. */
export interface MediaInfo {
  kind: "video" | "podcast";
  video_id: string | null;
  audio_url: string | null;
  duration_s: number;
}

export type ContentStatus = "transcribing" | "analysing" | "ready" | "refused" | "failed";

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
  /** `start_s`: a transcript paragraph's start in the recording. */
  paragraphs: { id: string; text: string; start_s?: number | null }[];
  /**
   * "analysing": fetched, notes not ready (two-phase "Open here"). "transcribing": a recording
   * with no transcript yet (no paragraphs). "refused" (with `refusal`) and "failed" (attempts used
   * up): the page shows the message with "Open original" and stops calling. Older APIs omit it.
   */
  status?: ContentStatus;
  media?: MediaInfo | null;
  refusal?: { code: string; message: string } | null;
  /** A reader's stored page that missed concept growth: POST .../grow once, then reload notes. */
  grow_pending?: boolean;
}

export type GrowStatus = "none" | "capped" | "grown" | "growing";

export interface AnnotationsResponse {
  content_id: string;
  persona: PersonaKey | null;
  density: Density;
  count: number;
  /** Span annotations only, ranked. */
  annotations: CardAnnotation[];
  /** Paragraph markers and the "Know this?" prompt, drawn by the annotator. */
  extras: (ParagraphMarker | PromptAnnotation)[];
  /** The pre-read card, drawn above the article. */
  preread: PrereadAnnotation | null;
}

type RawAnnotations = Omit<AnnotationsResponse, "annotations" | "extras" | "preread"> & {
  annotations: (CardAnnotation | ParagraphMarker | PromptAnnotation | PrereadAnnotation)[];
};

function splitAnnotations(raw: RawAnnotations): AnnotationsResponse {
  const spans: CardAnnotation[] = [];
  const extras: AnnotationsResponse["extras"] = [];
  let preread: PrereadAnnotation | null = null;
  for (const a of raw.annotations) {
    if (a.kind === "span") spans.push(a as CardAnnotation);
    else if (a.kind === "preread") preread = a as PrereadAnnotation;
    else extras.push(a as ParagraphMarker | PromptAnnotation);
  }
  return { ...raw, annotations: spans, extras, preread };
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
  /** Opens in Gloss (articles; videos within the media caps). Older APIs omit it: articles only. */
  open_here?: boolean;
}

export interface RecsResponse {
  content_id: string;
  persona: PersonaKey | null;
  prefer: RecFormat | null;
  items: RecItem[];
  pending: boolean;
  web_formats: RecFormat[];
}

/** Whether an item opens in Gloss: the server's `open_here` (R11); older APIs: articles only. */
export function opensHere(item: { format: RecFormat; open_here?: boolean }): boolean {
  return item.open_here ?? item.format === "article";
}

export type ApiErrorKind = "not_found" | "unauthorized" | "server" | "offline" | "pending";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
    readonly detail?: string,
  ) {
    super(detail ?? `api ${kind}${status ? ` ${status}` : ""}`);
  }
}

export type ReaderEventType =
  | "article_helpful"
  | "explain_opened"
  | "knew_this"
  | "explain_helpful"
  | "annotation_dismissed"
  | "text_searched"
  | "paragraph_dwell";

/** POST /v1/explain (DESIGN §7): a verified two-part card, or the definition only. */
export interface ExplanationResponse {
  id: string;
  kind: "verified" | "definition";
  mode: "span" | "paragraph";
  label: string;
  definition: string;
  background: string | null;
  author_says: string | null;
  analogy_domain: string | null;
  band?: string;
  can_simpler?: boolean;
  can_deeper?: boolean;
  cached: boolean;
  /** The analogy frames on offer and the one used (decision 67 A3). */
  frames?: { pick: string | null; for_you: string | null; used: "pick" | "for_you" };
  /** The daily explanation cap was reached: a definition card, not a verdict on the note. */
  capped?: boolean;
}

export interface ReaderEvent {
  id: string;
  type: ReaderEventType;
  at: string;
  concept_id: string | null;
  content_id: string | null;
  paragraph_id?: string;
  words?: number;
  ms?: number;
}

/** What POST /v1/explain explains: a span (demand) or a whole paragraph. */
/** `frame: "for_you"`: the Background in a frame from the reader's map (decision 67 A3). */
export type ExplainTarget =
  | { demand_id: string; shift?: -1 | 1; frame?: "for_you" }
  | { paragraph_id: string; frame?: "for_you" };

/** The API's origin in production (Cloud Run); empty locally, where Vite proxies /v1. */
const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? "").replace(/\/$/, "");

function kindOf(status: number): ApiErrorKind {
  if (status === 409) return "pending";
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
  if (res.status === 204) return null as T; // e.g. DELETE /v1/me/goals/{id}
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown, signal?: AbortSignal) => send<T>("POST", path, body, signal);

export function errorKind(error: unknown): ApiErrorKind {
  return error instanceof ApiError ? error.kind : "offline";
}

/** Demo readers carry a persona; signed-in readers are themselves (no persona param). */
const personaParam = (persona: PersonaKey | null) => (persona ? `&persona=${persona}` : "");
const personaQuery = (persona: PersonaKey | null) => (persona ? `?persona=${persona}` : "");

export const api = {
  /** Low-level helpers for feature modules (lib/profileApi.ts). */
  raw: { get, send },
  library: (q: string, persona: PersonaKey | null, density: Density, signal?: AbortSignal) =>
    get<ContentSummary[]>(
      `/v1/content?q=${encodeURIComponent(q)}&density=${density}${personaParam(persona)}`,
      signal,
    ),
  content: (id: string, signal?: AbortSignal) =>
    get<ContentDetail>(`/v1/content/${encodeURIComponent(id)}`, signal),
  recommendations: (
    id: string,
    persona: PersonaKey | null,
    prefer: RecFormat | null,
    signal?: AbortSignal,
    /** "article": the card chips, from the article's key ideas (decision 67 N1). */
    basis: "consumer" | "article" = "consumer",
  ) =>
    get<RecsResponse>(
      `/v1/content/${encodeURIComponent(id)}/recommendations?${prefer ? `prefer=${prefer}` : ""}${basis === "article" ? `${prefer ? "&" : ""}basis=article` : ""}${personaParam(persona)}`,
      signal,
    ),
  recEvents: (persona: PersonaKey | null, events: { id: string; type: RecEventType; item_id: string }[]) =>
    post<{ applied: number; ignored: number }>("/v1/recs/events", { persona, events }),
  openWeb: (url: string, signal?: AbortSignal) =>
    post<{ content_id: string; new: boolean; ready?: boolean; kind?: RecFormat }>("/v1/recs/open", { url }, signal),
  /** A recording's transcript: 200 done (then analyse), 202 another request is on it (retry). */
  transcribe: async (id: string, signal?: AbortSignal): Promise<"done" | "transcribing"> => {
    const res = await request(
      `/v1/content/${encodeURIComponent(id)}/transcribe`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      signal,
    );
    if (res.status === 202) return "transcribing";
    if (!res.ok) throw await failure(res);
    return "done";
  },
  /** Phase 2 of "Open here": 200 ready, 202 another request is analysing it (retry). */
  analyse: async (id: string, signal?: AbortSignal): Promise<"ready" | "analysing"> => {
    const res = await request(
      `/v1/content/${encodeURIComponent(id)}/analyse`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      signal,
    );
    if (res.status === 202) return "analysing";
    if (!res.ok) throw await failure(res);
    return "ready";
  },
  /** Grow a page that missed concept growth (M9): 202 means another request is on it. */
  grow: async (id: string, signal?: AbortSignal): Promise<GrowStatus> => {
    const res = await request(
      `/v1/content/${encodeURIComponent(id)}/grow`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      signal,
    );
    if (res.status === 202) return "growing";
    if (!res.ok) throw await failure(res);
    return ((await res.json()) as { status: GrowStatus }).status;
  },
  /** Current bands for the recap (Design pass A4). */
  bands: (conceptIds: string[], persona: PersonaKey | null) =>
    post<Record<string, string>>(`/v1/me/bands${personaQuery(persona)}`, { concept_ids: conceptIds.slice(0, 50) }),
  /** "Know this?" answer: the reader's own word, strong evidence (DESIGN §6.5). */
  correct: (conceptId: string, known: boolean, persona: PersonaKey | null) =>
    send<{ concept_id: string; band: string; p_know: number }>(
      "PATCH",
      `/v1/me/graph/${encodeURIComponent(conceptId)}${personaQuery(persona)}`,
      { state: known ? "known" : "unknown" },
    ),
  /** `refresh`: refetched after a "Know this?" answer (46d): no new prompt, not a new page view. */
  annotations: (
    id: string, persona: PersonaKey | null, density: Density, debug: boolean, signal?: AbortSignal, refresh = false,
  ) =>
    get<RawAnnotations>(
      `/v1/content/${encodeURIComponent(id)}/annotations?density=${density}${personaParam(persona)}${debug ? "&debug=1" : ""}${refresh ? "&refresh=1" : ""}`,
      signal,
    ).then(splitAnnotations),
  explain: (contentId: string, target: ExplainTarget, persona: PersonaKey | null) =>
    post<ExplanationResponse>(`/v1/explain${personaQuery(persona)}`, {
      content_id: contentId,
      ...target,
    }),
  reportExplanation: (
    explanationId: string,
    report: { event_id: string; content_id: string; concept_id: string | null },
    persona: PersonaKey | null,
  ) =>
    post<{ evicted: boolean; event_applied: boolean }>(
      `/v1/explain/${encodeURIComponent(explanationId)}/report${personaQuery(persona)}`,
      report,
    ),
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

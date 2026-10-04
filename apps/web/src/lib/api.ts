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

export type ApiErrorKind = "not_found" | "unauthorized" | "server" | "offline";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
  ) {
    super(`api ${kind}${status ? ` ${status}` : ""}`);
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
  annotations: (id: string, persona: PersonaKey, density: Density, debug: boolean, signal?: AbortSignal) =>
    get<AnnotationsResponse>(
      `/v1/content/${encodeURIComponent(id)}/annotations?persona=${persona}&density=${density}${debug ? "&debug=1" : ""}`,
      signal,
    ),
};

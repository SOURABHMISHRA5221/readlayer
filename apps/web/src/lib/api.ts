import type { CardAnnotation } from "@readlayer/annotator";

import type { Density, PersonaKey } from "./personas";

export interface ContentSummary {
  id: string;
  title: string;
  site: string;
  word_count: number;
}

export interface ContentDetail extends ContentSummary {
  url: string;
  paragraphs: { id: string; text: string }[];
}

export interface AnnotationsResponse {
  content_id: string;
  persona: PersonaKey;
  density: Density;
  count: number;
  annotations: CardAnnotation[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) {
    const message =
      res.status === 404
        ? "That article isn't in the library."
        : res.status === 401
          ? "The API wants a sign-in. Run it with `make dev` (dev auth bypass)."
          : `The API answered ${res.status}.`;
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

export const api = {
  library: (q: string, signal?: AbortSignal) =>
    get<ContentSummary[]>(`/v1/content?q=${encodeURIComponent(q)}`, signal),
  content: (id: string, signal?: AbortSignal) =>
    get<ContentDetail>(`/v1/content/${encodeURIComponent(id)}`, signal),
  annotations: (
    id: string,
    persona: PersonaKey,
    density: Density,
    debug: boolean,
    signal?: AbortSignal,
  ) =>
    get<AnnotationsResponse>(
      `/v1/content/${encodeURIComponent(id)}/annotations?persona=${persona}&density=${density}${debug ? "&debug=1" : ""}`,
      signal,
    ),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Couldn't reach the API. Is `make dev` running?";
}

import type { CardAnnotation, Explanation } from "@readlayer/annotator";

import { api } from "./api";
import type { PersonaKey } from "./personas";

/**
 * Verified explanations for span cards (DESIGN §7). One request per (persona, article, span)
 * per page session; the top spans are fetched as soon as the annotations arrive, so their
 * first hover fills at once, and the rest load when their card opens. A failed load is
 * forgotten so the next open tries again; the card shows the definition meanwhile.
 */
export const PREFETCH_TOP = 3;

const cache = new Map<string, Promise<Explanation>>();

const keyOf = (persona: PersonaKey | null, contentId: string, annotationId: string) =>
  `${persona ?? "me"}|${contentId}|${annotationId}`;

export function loadExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
): Promise<Explanation> {
  const key = keyOf(persona, contentId, annotation.id);
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = api.explain(contentId, annotation.id, persona).then(
    (r): Explanation => ({
      id: r.id,
      kind: r.kind,
      background: r.background,
      author_says: r.author_says,
      analogy_domain: r.analogy_domain,
    }),
  );
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

/** Warm the cache for the highest-scoring spans. */
export function prefetchExplanations(
  contentId: string,
  persona: PersonaKey | null,
  annotations: readonly CardAnnotation[],
): void {
  const top = [...annotations]
    .filter((a) => a.kind === "span")
    .sort((a, b) => b.score - a.score)
    .slice(0, PREFETCH_TOP);
  for (const a of top) loadExplanation(contentId, persona, a).catch(() => undefined);
}

/** "This is wrong": evict server-side, record report_wrong, and drop our copy. */
export async function reportExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotationId: string,
  explanationId: string,
  conceptId: string | null,
): Promise<void> {
  cache.delete(keyOf(persona, contentId, annotationId));
  await api.reportExplanation(
    explanationId,
    { event_id: crypto.randomUUID(), content_id: contentId, concept_id: conceptId },
    persona,
  );
}

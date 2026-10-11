import type { CardAnnotation, Explanation } from "@readlayer/annotator";

import { api } from "./api";
import type { PersonaKey } from "./personas";

/**
 * Verified explanations for span and paragraph cards (DESIGN §7). One request per (persona, article, note)
 * per page session; the top spans are fetched as soon as the annotations arrive, so their
 * first hover fills at once, and the rest load when their card opens. A failed load is
 * forgotten so the next open tries again; the card shows the definition meanwhile.
 */
export const PREFETCH_TOP = 3;

const cache = new Map<string, Promise<Explanation>>();

const keyOf = (persona: PersonaKey | null, contentId: string, annotationId: string, shift = 0) =>
  `${persona ?? "me"}|${contentId}|${annotationId}|${shift}`;

const toExplanation = (r: Awaited<ReturnType<typeof api.explain>>): Explanation => ({
  id: r.id,
  kind: r.kind,
  background: r.background,
  author_says: r.author_says,
  analogy_domain: r.analogy_domain,
  band: r.band,
  can_simpler: r.can_simpler,
  can_deeper: r.can_deeper,
});

export function loadExplanation(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
): Promise<Explanation> {
  const key = keyOf(persona, contentId, annotation.id);
  const hit = cache.get(key);
  if (hit) return hit;
  // Paragraph markers are explained by paragraph; spans by their demand id.
  const target =
    annotation.kind === "paragraph" ? { paragraph_id: annotation.paragraph_id } : { demand_id: annotation.id };
  const pending = api.explain(contentId, target, persona).then(toExplanation);
  cache.set(key, pending);
  pending.catch(() => cache.delete(key));
  return pending;
}

/** "Say it simpler" / "Go deeper": only on click, never prefetched (Design pass A3). */
export function loadShifted(
  contentId: string,
  persona: PersonaKey | null,
  annotation: CardAnnotation,
  shift: -1 | 1,
): Promise<Explanation> {
  const key = keyOf(persona, contentId, annotation.id, shift);
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = api.explain(contentId, { demand_id: annotation.id, shift }, persona).then(toExplanation);
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
  for (const shift of [0, -1, 1]) cache.delete(keyOf(persona, contentId, annotationId, shift));
  await api.reportExplanation(
    explanationId,
    { event_id: crypto.randomUUID(), content_id: contentId, concept_id: conceptId },
    persona,
  );
}
